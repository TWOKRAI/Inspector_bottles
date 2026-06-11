"""Тесты RobotIoPlugin v2 — тонкий job-форвардер через DeviceHubClient.

ctx — mock (worker_manager no-op, forwarder зовём руками); DeviceHubClient —
фейковый (подменяем в configure/start). Реальный IPC не нужен.

Проверяем:
- process() кладёт job в deque (pass-through)
- forwarder шлёт через DeviceHubClient (успех/таймаут/drop при переполнении)
- once-per-transition лог
- конфиг device_id
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch


from Plugins.io.robot_io.plugin import RobotIoPlugin


# ------------------------------------------------------------------ #
# Фейковый DeviceHubClient
# ------------------------------------------------------------------ #


class FakeDeviceHubClient:
    """Фейковый IPC-клиент: request() возвращает заданный ответ."""

    def __init__(self, responses: list[dict] | None = None) -> None:
        # Очередь ответов; если пуста — {"status": "ok"}
        self._responses: list[dict] = list(responses or [])
        self.calls: list[tuple[str, dict]] = []

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        self.calls.append((command, args or {}))
        if self._responses:
            return self._responses.pop(0)
        return {"status": "ok"}


class FailingClient:
    """Клиент, который бросает исключение на каждом запросе."""

    def __init__(self, error_msg: str = "IPC ошибка") -> None:
        self._error_msg = error_msg
        self.call_count = 0

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        self.call_count += 1
        raise RuntimeError(self._error_msg)


# ------------------------------------------------------------------ #
# Фабрики
# ------------------------------------------------------------------ #


def make_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext."""
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.registers = None
    ctx.state_proxy = MagicMock()
    ctx.worker_manager.create_worker = MagicMock()
    return ctx


def make_plugin(
    *,
    client: FakeDeviceHubClient | FailingClient | None = None,
    device_id: str = "robot_main",
    maxlen: int = 64,
) -> tuple[RobotIoPlugin, MagicMock]:
    """Сконфигурированный и запущенный плагин с фейковым клиентом."""
    plugin = RobotIoPlugin()
    ctx = make_ctx({"device_id": device_id, "forward_deque_maxlen": maxlen})
    plugin.configure(ctx)
    # Подменяем клиент
    if client is None:
        client = FakeDeviceHubClient()
    with patch("Plugins.io.robot_io.plugin.DeviceHubClient", return_value=client):
        plugin.start(ctx)
    plugin._client = client  # гарантируем
    return plugin, ctx


# ------------------------------------------------------------------ #
# Тесты: lifecycle / конфиг
# ------------------------------------------------------------------ #


def test_configure_sets_device_id() -> None:
    """Конфиг device_id проставляется в register."""
    plugin, _ctx = make_plugin(device_id="my_robot")
    assert plugin._reg.device_id == "my_robot"


def test_start_creates_forwarder_worker() -> None:
    """start() создаёт worker job_forwarder."""
    plugin, ctx = make_plugin()
    ctx.worker_manager.create_worker.assert_called_once()
    assert ctx.worker_manager.create_worker.call_args.args[0] == "job_forwarder"


def test_shutdown_clears_deque() -> None:
    """shutdown() очищает deque и обнуляет клиент."""
    plugin, ctx = make_plugin()
    plugin._deque.append({"device_id": "r", "x_mm": 1.0, "y_mm": 2.0})
    plugin.shutdown(ctx)
    assert len(plugin._deque) == 0
    assert plugin._client is None


# ------------------------------------------------------------------ #
# Тесты: process() — извлечение и deque
# ------------------------------------------------------------------ #


def test_process_enqueues_job_from_item() -> None:
    """process() извлекает job из item[job_source] и кладёт в deque."""
    plugin, _ctx = make_plugin()
    items = [
        {"frame": "x", "robot_job": {"x_mm": 10.0, "y_mm": -5.0}},
        {"frame": "y"},  # без robot_job — пропуск
    ]
    out = plugin.process(items)
    assert out == items  # pass-through
    assert len(plugin._deque) == 1
    job = plugin._deque[0]
    assert job["x_mm"] == 10.0
    assert job["y_mm"] == -5.0
    assert job["device_id"] == "robot_main"
    assert plugin._reg.queue_len == 1


def test_process_drops_oldest_on_overflow() -> None:
    """При переполнении deque(maxlen) старые дропаются, счётчик растёт."""
    plugin, _ctx = make_plugin(maxlen=2)
    for i in range(3):
        plugin.process([{"robot_job": {"x_mm": float(i), "y_mm": 0.0}}])
    # maxlen=2: первый элемент (i=0) вытеснен третьим (i=2)
    assert len(plugin._deque) == 2
    assert plugin._deque[0]["x_mm"] == 1.0
    assert plugin._deque[1]["x_mm"] == 2.0
    assert plugin._reg.jobs_dropped == 1


def test_process_ignores_malformed_job() -> None:
    """Нет x_mm/y_mm — job не попадает в deque."""
    plugin, _ctx = make_plugin()
    plugin.process([{"robot_job": {"only_x": 1.0}}])
    assert len(plugin._deque) == 0


# ------------------------------------------------------------------ #
# Тесты: forwarder — успех / ошибка / once-per-transition
# ------------------------------------------------------------------ #


def test_forwarder_sends_job_success() -> None:
    """Forwarder забирает из deque и шлёт через DeviceHubClient; jobs_forwarded растёт."""
    client = FakeDeviceHubClient()
    plugin, _ctx = make_plugin(client=client)
    plugin._deque.append({"device_id": "robot_main", "x_mm": 25.0, "y_mm": -10.0})

    stop = threading.Event()
    pause = threading.Event()

    # Запускаем forwarder на короткое время
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True)
    worker.start()

    # Ждём пока deque опустеет
    for _ in range(200):
        if not plugin._deque:
            break
        threading.Event().wait(0.01)
    stop.set()
    worker.join(timeout=2.0)

    assert plugin._reg.jobs_forwarded == 1
    assert plugin._reg.queue_len == 0
    assert len(client.calls) == 1
    assert client.calls[0][0] == "robot_enqueue_job"
    assert client.calls[0][1]["x_mm"] == 25.0


def test_forwarder_handles_hub_error() -> None:
    """При ошибке hub — jobs_dropped+1, hub_errors+1, last_error заполнен."""
    client = FakeDeviceHubClient([{"status": "error", "message": "робот не подключён"}])
    plugin, _ctx = make_plugin(client=client)
    plugin._deque.append({"device_id": "robot_main", "x_mm": 1.0, "y_mm": 2.0})

    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True)
    worker.start()
    for _ in range(200):
        if not plugin._deque:
            break
        threading.Event().wait(0.01)
    stop.set()
    worker.join(timeout=2.0)

    assert plugin._reg.jobs_dropped == 1
    assert plugin._reg.hub_errors == 1
    assert "робот не подключён" in plugin._reg.last_error


def test_forwarder_exception_drops_job() -> None:
    """Исключение от клиента — jobs_dropped+1, hub_errors+1."""
    client = FailingClient("timeout")
    plugin, _ctx = make_plugin(client=client)
    plugin._deque.append({"device_id": "robot_main", "x_mm": 1.0, "y_mm": 2.0})

    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True)
    worker.start()
    for _ in range(200):
        if not plugin._deque:
            break
        threading.Event().wait(0.01)
    stop.set()
    worker.join(timeout=2.0)

    assert plugin._reg.jobs_dropped == 1
    assert plugin._reg.hub_errors == 1
    assert "timeout" in plugin._reg.last_error


def test_once_per_transition_logging() -> None:
    """Лог ошибки hub пишется только при смене состояния (once-per-transition)."""
    # Три подряд ошибки → лог только первый раз
    client = FakeDeviceHubClient(
        [
            {"status": "error", "message": "err1"},
            {"status": "error", "message": "err2"},
            {"status": "ok"},
        ]
    )
    plugin, ctx = make_plugin(client=client)
    for i in range(3):
        plugin._deque.append({"device_id": "robot_main", "x_mm": float(i), "y_mm": 0.0})

    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True)
    worker.start()
    for _ in range(300):
        if plugin._reg.jobs_forwarded >= 1:
            break
        threading.Event().wait(0.01)
    stop.set()
    worker.join(timeout=2.0)

    # Были 2 ошибки + 1 успех
    assert plugin._reg.jobs_dropped == 2
    assert plugin._reg.jobs_forwarded == 1

    # Проверяем лог-вызовы: ошибка 1 раз + восстановление 1 раз
    error_calls = [c for c in ctx.log_error.call_args_list if "hub" in str(c)]
    info_calls = [c for c in ctx.log_info.call_args_list if "восстановлен" in str(c)]
    assert len(error_calls) == 1, f"Ожидалась 1 ошибка hub, получено {len(error_calls)}"
    assert len(info_calls) == 1, f"Ожидалось 1 восстановление, получено {len(info_calls)}"


# ------------------------------------------------------------------ #
# Тесты: no commands
# ------------------------------------------------------------------ #


def test_no_commands() -> None:
    """Плагин v2 не имеет команд."""
    assert RobotIoPlugin.commands == {}
