"""Тесты RobotIoPlugin — владелец соединения + feeder.

ctx — mock (worker_manager no-op, feeder зовём руками); транспорт —
FakeRobotTransport (фейк-робот, без сети). Реальный RobotClient подменяется
инъекцией transport через фабрику плагина.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from Plugins.io.robot_io.plugin import RobotIoPlugin

from Services.robot_comm import RobotClient, RobotConfig, runtime
from Services.robot_comm.testing.fake_transport import FakeRobotTransport


@pytest.fixture(autouse=True)
def _clean_runtime():
    runtime.clear()
    yield
    runtime.clear()


def make_ctx(config: dict | None = None) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config or {}
    ctx.registers = None  # локальный register
    ctx.state_proxy = MagicMock()
    ctx.worker_manager.create_worker = MagicMock()
    return ctx


def make_plugin(config: dict | None = None) -> tuple[RobotIoPlugin, MagicMock, FakeRobotTransport]:
    """Сконфигурированный и запущенный плагин с фейк-транспортом."""
    plugin = RobotIoPlugin()
    ctx = make_ctx(config)
    plugin.configure(ctx)
    # Инъекция фейк-транспорта: подменяем фабрику клиента в start()
    transport = FakeRobotTransport()
    real_client = RobotClient(RobotConfig(), transport=transport)
    with patch("Plugins.io.robot_io.plugin.RobotClient", return_value=real_client):
        plugin.start(ctx)
    return plugin, ctx, transport


# --- lifecycle / владение ---


def test_start_publishes_client_to_runtime() -> None:
    plugin, _ctx, _t = make_plugin()
    assert runtime.peek_client() is not None
    assert runtime.get_client().is_connected  # auto_connect=True


def test_start_creates_feeder_worker() -> None:
    plugin, ctx, _t = make_plugin()
    ctx.worker_manager.create_worker.assert_called_once()
    assert ctx.worker_manager.create_worker.call_args.args[0] == "robot_feeder"


def test_shutdown_clears_runtime_and_disconnects() -> None:
    plugin, ctx, _t = make_plugin()
    client = runtime.peek_client()
    plugin.shutdown(ctx)
    assert runtime.peek_client() is None
    assert not client.is_connected


# --- очередь / process ---


def test_process_enqueues_job_from_item() -> None:
    plugin, _ctx, _t = make_plugin()
    items = [{"frame": "x", "robot_job": {"x_mm": 10.0, "y_mm": -5.0}}, {"frame": "y"}]
    out = plugin.process(items)
    assert out == items  # pass-through
    assert plugin._reg.queue_len == 1
    x, y, ecap = plugin._queue[0]
    assert (x, y) == (10.0, -5.0)
    assert isinstance(ecap, int)  # энкодер снят в момент постановки


def test_cmd_send_test_job_and_clear() -> None:
    plugin, _ctx, _t = make_plugin()
    result = plugin.cmd_send_test_job({"x": 50, "y": 60})
    assert result["status"] == "ok"
    assert result["queue_len"] == 1
    cleared = plugin.cmd_clear_queue({})
    assert cleared["dropped"] == 1
    assert plugin._reg.queue_len == 0


def test_cmd_send_test_job_validates() -> None:
    plugin, _ctx, _t = make_plugin()
    assert plugin.cmd_send_test_job({"x": "abc"})["status"] == "error"


# --- feeder ---


def test_feeder_delivers_job() -> None:
    """Один реальный цикл feeder: задание уходит, выполняется, jobs_done растёт."""
    plugin, _ctx, _t = make_plugin()
    plugin._reg.feed_poll_s = 0.005
    plugin.cmd_send_test_job({"x": 25.0, "y": -10.0})
    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._feeder_loop, args=(stop, pause), daemon=True)
    worker.start()
    deadline = threading.Event()
    for _ in range(200):
        if plugin._reg.jobs_done >= 1:
            break
        deadline.wait(0.01)
    stop.set()
    worker.join(timeout=2.0)
    assert plugin._reg.jobs_done == 1
    assert plugin._reg.queue_len == 0
    echo = runtime.get_client().read_echo()
    assert echo.job_x == pytest.approx(25.0)


def test_manual_mode_pauses_feeding() -> None:
    plugin, _ctx, _t = make_plugin()
    plugin._reg.feed_poll_s = 0.005
    plugin.cmd_set_manual_mode({"on": True})
    plugin.cmd_send_test_job({"x": 1.0, "y": 1.0})
    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._feeder_loop, args=(stop, pause), daemon=True)
    worker.start()
    threading.Event().wait(0.1)
    stop.set()
    worker.join(timeout=2.0)
    assert plugin._reg.jobs_sent == 0  # ручной режим: ничего не отдано
    assert plugin._reg.queue_len == 1


# --- команды ---


def test_cmd_abort_and_mode_and_servo() -> None:
    plugin, _ctx, _t = make_plugin()
    assert plugin.cmd_abort({"mode": 1})["status"] == "ok"
    assert plugin.cmd_set_mode({"mode": "draw"})["status"] == "ok"
    assert plugin._reg.mode == "draw"
    assert plugin.cmd_set_servo({"on": False})["status"] == "ok"


def test_cmd_robot_config_roundtrip() -> None:
    plugin, _ctx, _t = make_plugin()
    assert plugin.cmd_set_robot_config({"speed": 60, "pick_z": -3.5})["status"] == "ok"
    result = plugin.cmd_get_robot_config({})
    assert result["status"] == "ok"
    assert result["config"]["speed"] == 60
    assert result["config"]["pick_z"] == pytest.approx(-3.5)


def test_cmd_get_telemetry() -> None:
    plugin, _ctx, _t = make_plugin()
    result = plugin.cmd_get_telemetry({})
    assert result["status"] == "ok"
    assert "telemetry" in result and "encoder" in result


def test_commands_error_when_disconnected() -> None:
    plugin, ctx, _t = make_plugin()
    runtime.get_client().disconnect()
    assert plugin.cmd_abort({})["status"] == "error"
    assert plugin.cmd_send_test_job({"x": 1, "y": 2})["status"] == "error"
