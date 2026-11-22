"""C-104 на настоящих объектах: PluginContext + HealthState/HealthReporter + две плоскости.

Остальные тесты robot_io гоняют форвардер на `MagicMock`-контексте: мок молча принимает
любой вызов и не отличает «голос дошёл до файла» от «метод вызван». Здесь контекст
настоящий (`PluginContext`), health настоящий (`ctx.health` -> `HealthState`, окно голосов,
предохранитель), а плоскости логов и ошибок — РАЗНЫЕ объекты по образцу
`multiprocess_framework/modules/process_module/tests/test_error_route.py` (общий дубль на обе
плоскости дал бы зелёное при любой маршрутизации).

Проверяется наблюдаемый эффект: какая строка попала в плоскость логов, какой инцидент — в
плоскость ошибок, что записано в state.
"""

from __future__ import annotations

import threading
from typing import Any

from multiprocess_framework.modules.base_manager import ObservableMixin
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from Plugins.io.robot_io.plugin import RobotIoPlugin

_SERVO_REFUSED = {"status": "error", "message": "робот остановлен: включите серво"}
_PUBLISH_FAIL_LINE = "RobotIoPlugin: сбой публикации state robot_io"


class _Plane:
    """Дубль плоскости: помнит записи логов (уровень, текст) и инциденты ошибок."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []
        self.incidents: list[tuple[str, str, dict]] = []

    def _rec(self, level: str, message: Any) -> None:
        self.records.append((level, str(message)))

    def debug(self, message: Any, **kw: Any) -> None:
        self._rec("DEBUG", message)

    def info(self, message: Any, **kw: Any) -> None:
        self._rec("INFO", message)

    def warning(self, message: Any, **kw: Any) -> None:
        self._rec("WARNING", message)

    def error(self, message: Any, **kw: Any) -> None:
        self._rec("ERROR", message)

    def critical(self, message: Any, **kw: Any) -> None:
        self._rec("CRITICAL", message)

    def track_error(self, exc: BaseException, context: Any = None) -> None:
        self.incidents.append((type(exc).__name__, str(exc), dict(context or {})))


class _Services:
    """Процесс с двумя разными плоскостями (логи / ошибки) и записывающим state_proxy."""

    def __init__(self) -> None:
        self.name = "layout"
        self.logs = _Plane()
        self.errors = _Plane()
        managers = {"logger": self.logs, "error": self.errors}

        class _Host(ObservableMixin):
            def __init__(self, mgrs: dict) -> None:
                ObservableMixin.__init__(self, managers=mgrs)

        self._host = _Host(managers)
        self.worker_manager = None
        self.state_proxy = _StateProxy()

    def log_debug(self, message: str, **kw: Any) -> None:
        self._host._log_debug(message, **kw)

    def log_info(self, message: str, **kw: Any) -> None:
        self._host._log_info(message, **kw)

    def log_warning(self, message: str, **kw: Any) -> None:
        self._host._log_warning(message, **kw)

    def log_error(self, message: str, **kw: Any) -> None:
        self._host._log_error(message, **kw)

    def log_critical(self, message: str, **kw: Any) -> None:
        self._host._log_critical(message, **kw)

    def track_error(self, exc: BaseException, context: Any = None) -> None:
        self._host._track_error(exc, context)


class _StateProxy:
    """merge() пишет вызовы; при `fail=True` бросает (как оборванный канал state)."""

    def __init__(self) -> None:
        self.fail = False
        self.merges: list[tuple[str, dict]] = []

    def merge(self, path: str, data: dict, *args: Any, **kwargs: Any) -> None:
        if self.fail:
            raise ConnectionError("state недоступен")
        self.merges.append((path, dict(data)))


class _Client:
    """Фейковый клиент хаба: отвечает по списку; BaseException из списка бросается."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        self.calls.append((command, dict(args or {})))
        reply = self.responses.pop(0) if self.responses else {"status": "ok"}
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _make_plugin() -> tuple[RobotIoPlugin, PluginContext, _Services, _Client]:
    services = _Services()
    ctx = PluginContext(
        services=services,
        config={"device_id": "robot_main", "forward_deque_maxlen": 64},
        plugin_name="robot_io",
    )
    ctx.state_proxy = services.state_proxy
    plugin = RobotIoPlugin()
    plugin.configure(ctx)
    client = _Client([])
    plugin._client = client
    return plugin, ctx, services, client


def _job(char: str, slot: int) -> dict:
    return {"robot_job": {"pick_x_mm": 1.0, "pick_y_mm": 2.0, "char": char, "slot": slot}}


def _run_forwarder(plugin: RobotIoPlugin, client: _Client, total_calls: int) -> None:
    """Форвардер в daemon-потоке с join-дедлайном; проверки — после join."""
    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True)
    worker.start()
    for _ in range(300):
        if len(client.calls) >= total_calls and not plugin._deque:
            break
        threading.Event().wait(0.01)
    stop.set()
    worker.join(timeout=2.0)
    assert not worker.is_alive(), "форвардер не остановился"


def test_real_health_two_refusals_two_voices() -> None:
    """Два отказа-статуса подряд -> две строки в плоскости логов и два инцидента в плоскости ошибок.

    Краснеет при `throttle=0.0 -> None` в ветке отказа: окно health схлопнёт второй
    голос (тот же класс и context), в логах останется одна строка.
    """
    plugin, ctx, services, client = _make_plugin()
    client.responses = [dict(_SERVO_REFUSED), dict(_SERVO_REFUSED)]
    plugin.process([_job("М", 0)])
    plugin.process([_job("А", 1)])

    _run_forwarder(plugin, client, total_calls=2)

    health_lines = [text for _level, text in services.logs.records if "[health]" in text]
    assert health_lines == [
        "[health] ResourceUnavailable @ robot_io.forward.refused: "
        "hub отказ (буква 'М', ячейка 0): робот остановлен: включите серво",
        "[health] ResourceUnavailable @ robot_io.forward.refused: "
        "hub отказ (буква 'А', ячейка 1): робот остановлен: включите серво",
    ]
    assert [(etype, msg) for etype, msg, _ctx in services.errors.incidents] == [
        ("ResourceUnavailable", "hub отказ (буква 'М', ячейка 0): робот остановлен: включите серво"),
        ("ResourceUnavailable", "hub отказ (буква 'А', ячейка 1): робот остановлен: включите серво"),
    ]
    # ctx.log_error не использован: в плоскости логов нет записей уровня ERROR.
    assert [text for level, text in services.logs.records if level == "ERROR"] == []
    assert ctx.health.error_count == 2
    # Подпись в хаб не уходит.
    assert all("_label" not in args for _cmd, args in client.calls)
    assert plugin._reg.last_dropped_job == "буква 'А', ячейка 1: робот остановлен: включите серво"


def test_publish_failure_warns_once_per_transition() -> None:
    """Сбой state_proxy.merge: одна строка log_warning на переход, форвардер не встал.

    Три исхода подряд (успех, отказ-статус, отказ-исключение) при падающем merge -> одна
    строка; успешная публикация снимает флаг -> следующий сбой даёт вторую строку.
    """
    plugin, ctx, services, client = _make_plugin()
    proxy = services.state_proxy
    proxy.fail = True
    client.responses = [{"status": "ok"}, dict(_SERVO_REFUSED), RuntimeError("таймаут IPC")]
    for job in (_job("М", 0), _job("А", 1), _job("Р", 2)):
        plugin.process([job])

    _run_forwarder(plugin, client, total_calls=3)

    def publish_lines() -> list[str]:
        return [text for level, text in services.logs.records if _PUBLISH_FAIL_LINE in text and level == "WARNING"]

    # Форвардер переслал все три задания, каждое дошло до хаба.
    assert len(client.calls) == 3
    assert plugin._reg.jobs_forwarded == 1
    assert plugin._reg.jobs_dropped == 2
    assert publish_lines() == [f"{_PUBLISH_FAIL_LINE}: ConnectionError: state недоступен"]
    # Сбой публикации не кормит health: в health два инцидента заданий, не пять.
    assert ctx.health.error_count == 2
    assert len(services.errors.incidents) == 2

    # Публикация восстановилась -> флаг снят; затем снова сбой -> вторая строка.
    proxy.fail = False
    client.responses = [{"status": "ok"}]
    plugin.process([_job("И", 3)])
    _run_forwarder(plugin, client, total_calls=4)
    assert len(proxy.merges) == 1
    assert len(publish_lines()) == 1

    proxy.fail = True
    client.responses = [{"status": "ok"}]
    plugin.process([_job("Й", 4)])
    _run_forwarder(plugin, client, total_calls=5)
    assert publish_lines() == [f"{_PUBLISH_FAIL_LINE}: ConnectionError: state недоступен"] * 2
