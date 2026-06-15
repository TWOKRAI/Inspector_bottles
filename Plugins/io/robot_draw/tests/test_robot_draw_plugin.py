"""Тесты RobotDrawPlugin — приёмник точек: формат robot_draw_polyline + forwarder."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from Plugins.io.robot_draw.plugin import RobotDrawPlugin


class FakeDeviceHubClient:
    """Фейковый IPC-клиент: запоминает вызовы, отдаёт заданные ответы."""

    def __init__(self, responses: list[dict] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[tuple[str, dict]] = []

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        self.calls.append((command, args or {}))
        return self._responses.pop(0) if self._responses else {"status": "ok"}


def make_ctx(config: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.registers = None
    ctx.state_proxy = MagicMock()
    ctx.worker_manager.create_worker = MagicMock()
    return ctx


def make_plugin(*, client=None, device_id: str = "robot_main") -> tuple[RobotDrawPlugin, MagicMock]:
    plugin = RobotDrawPlugin()
    ctx = make_ctx({"device_id": device_id})
    plugin.configure(ctx)
    if client is None:
        client = FakeDeviceHubClient()
    with patch("Plugins.io.robot_draw.plugin.DeviceHubClient", return_value=client):
        plugin.start(ctx)
    plugin._client = client
    return plugin, ctx


def test_send_requires_arm() -> None:
    """Без команды robot_draw_send process НЕ отправляет (даже при валидных точках)."""
    plugin, _ctx = make_plugin()
    pts = [{"x_mm": 1.0, "y_mm": 2.0, "pen": 0}, {"x_mm": 3.0, "y_mm": 4.0}]
    plugin.process([{"frame": "F", "draw_points": pts}])
    assert plugin._queue.empty()  # не отправлено без arming


def test_cmd_send_then_enqueues_once() -> None:
    plugin, _ctx = make_plugin()
    resp = plugin.cmd_send({})
    assert resp["status"] == "ok" and resp["armed"] is True
    pts = [{"x_mm": 1.0, "y_mm": 2.0, "pen": 0}, {"x_mm": 3.0, "y_mm": 4.0}]
    out = plugin.process([{"frame": "F", "draw_points": pts}])
    assert out[0]["frame"] == "F"  # pass-through
    task = plugin._queue.get_nowait()
    assert task["device_id"] == "robot_main"
    assert task["points"][0] == {"x_mm": 1.0, "y_mm": 2.0, "pen": 0}
    assert task["points"][1]["pen"] == 1  # дефолт pen
    # Одноразово: следующий кадр без новой команды не отправляет
    plugin.process([{"draw_points": pts}])
    assert plugin._queue.empty()


def test_process_ignores_empty_points() -> None:
    plugin, _ctx = make_plugin()
    plugin.cmd_send({})
    plugin.process([{"frame": "F"}, {"draw_points": []}])
    assert plugin._queue.empty()


def test_start_creates_forwarder_worker() -> None:
    plugin, ctx = make_plugin()
    ctx.worker_manager.create_worker.assert_called_once()
    assert ctx.worker_manager.create_worker.call_args.args[0] == "draw_forwarder"


def test_forwarder_sends_draw_polyline() -> None:
    client = FakeDeviceHubClient()
    plugin, _ctx = make_plugin(client=client)
    plugin._queue.put({"device_id": "robot_main", "points": [{"x_mm": 1.0, "y_mm": 2.0, "pen": 1}]})

    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True)
    worker.start()
    for _ in range(200):
        if plugin._reg.jobs_sent >= 1:
            break
        threading.Event().wait(0.01)
    stop.set()
    worker.join(timeout=2.0)

    assert plugin._reg.jobs_sent == 1
    assert plugin._reg.points_total == 1
    assert len(client.calls) == 1
    assert client.calls[0][0] == "robot_draw_polyline"
    assert client.calls[0][1]["device_id"] == "robot_main"


def test_forwarder_handles_hub_error() -> None:
    client = FakeDeviceHubClient([{"status": "error", "message": "робот не подключён"}])
    plugin, _ctx = make_plugin(client=client)
    plugin._queue.put({"device_id": "robot_main", "points": [{"x_mm": 1.0, "y_mm": 2.0, "pen": 1}]})

    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True)
    worker.start()
    for _ in range(200):
        if plugin._reg.hub_errors >= 1:
            break
        threading.Event().wait(0.01)
    stop.set()
    worker.join(timeout=2.0)

    assert plugin._reg.hub_errors == 1
    assert "робот не подключён" in plugin._reg.last_error


def test_has_send_command() -> None:
    assert RobotDrawPlugin.commands == {"robot_draw_send": "cmd_send"}


def test_pipeline_trigger_arms_then_sends() -> None:
    """Pipeline-триггер: сигнал на trigger_source взводит (как cmd_send), путь уходит
    на ближайшем кадре с точками (сигнал и точки — в разных process()-вызовах)."""
    plugin = RobotDrawPlugin()
    ctx = make_ctx({"device_id": "robot_main", "trigger_source": "out_1"})
    plugin.configure(ctx)
    client = FakeDeviceHubClient()
    with patch("Plugins.io.robot_draw.plugin.DeviceHubClient", return_value=client):
        plugin.start(ctx)
    plugin._client = client

    assert plugin._reg.trigger_source == "out_1"
    pts = [{"x_mm": 1.0, "y_mm": 2.0, "pen": 1}]
    # Кадр сигнала (без точек) — взводит armed, ничего не шлёт.
    plugin.process([{"out_1": True}])
    assert plugin._queue.empty()
    assert plugin._armed is True
    # Ближайший кадр с точками — отправляет (одноразово).
    plugin.process([{"draw_points": pts}])
    assert not plugin._queue.empty()
    plugin._queue.get_nowait()
    # Дальше без нового сигнала — не шлёт.
    plugin.process([{"draw_points": pts}])
    assert plugin._queue.empty()


def test_no_pipeline_trigger_when_source_empty() -> None:
    """trigger_source пуст (дефолт) — сигнал в item НЕ взводит (только команда)."""
    plugin, _ctx = make_plugin()  # trigger_source=""
    assert plugin._reg.trigger_source == ""
    plugin.process([{"out_1": True, "draw_points": [{"x_mm": 1.0, "y_mm": 2.0}]}])
    assert plugin._queue.empty()
    assert plugin._armed is False
