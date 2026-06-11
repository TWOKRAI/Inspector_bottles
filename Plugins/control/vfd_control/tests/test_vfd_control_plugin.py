"""Тесты VfdControlPlugin — потребитель моста через runtime robot_comm."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from Plugins.control.vfd_control.plugin import VfdControlPlugin

from Services.robot_comm import RobotClient, RobotConfig, runtime
from Services.robot_comm.testing.fake_transport import FakeRobotTransport


@pytest.fixture(autouse=True)
def _clean_runtime():
    runtime.clear()
    yield
    runtime.clear()


def make_ctx() -> MagicMock:
    ctx = MagicMock()
    ctx.config = {}
    ctx.registers = None
    ctx.state_proxy = MagicMock()
    ctx.worker_manager.create_worker = MagicMock()
    return ctx


def publish_robot() -> RobotClient:
    """Опубликовать подключённого фейк-робота как владелец (имитация robot_io)."""
    client = RobotClient(RobotConfig(), transport=FakeRobotTransport())
    client.connect()
    runtime.set_client(client)
    return client


def make_plugin() -> tuple[VfdControlPlugin, MagicMock]:
    plugin = VfdControlPlugin()
    ctx = make_ctx()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx


# --- lifecycle ---


def test_start_creates_poll_worker() -> None:
    _plugin, ctx = make_plugin()
    ctx.worker_manager.create_worker.assert_called_once()
    assert ctx.worker_manager.create_worker.call_args.args[0] == "vfd_poll"


def test_commands_error_without_owner() -> None:
    """Владелец robot_io не стартовал — команды отвечают ошибкой, не падают."""
    plugin, _ctx = make_plugin()
    result = plugin.cmd_run({"freq": 10})
    assert result["status"] == "error"
    assert "robot_io" in result["message"]


# --- команды через мост ---


def test_run_stop_via_bridge() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    assert plugin.cmd_run({"freq": 50.0})["status"] == "ok"
    status = plugin.cmd_get_status({})
    assert status["status"] == "ok"
    assert status["vfd"]["running"] is True
    assert status["vfd"]["out_freq_hz"] == pytest.approx(50.0)
    assert plugin.cmd_stop({})["status"] == "ok"
    assert plugin.cmd_get_status({})["vfd"]["running"] is False


def test_run_reverse_and_set_freq() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    assert plugin.cmd_run({"freq": 20.0, "reverse": True})["status"] == "ok"
    assert plugin.cmd_set_freq({"hz": 30.0})["status"] == "ok"
    assert plugin.cmd_get_status({})["vfd"]["out_freq_hz"] == pytest.approx(30.0)


def test_freq_validation_via_config() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    result = plugin.cmd_run({"freq": 99.0})  # выше freq_max_hz=50
    assert result["status"] == "error"
    assert "диапазона" in result["message"]


def test_set_freq_requires_hz() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    assert plugin.cmd_set_freq({})["status"] == "error"


def test_reset_fault() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    assert plugin.cmd_reset_fault({})["status"] == "ok"


# --- poll-worker ---


def test_poll_loop_updates_registers_and_state() -> None:
    publish_robot()
    plugin, ctx = make_plugin()
    plugin._reg.poll_interval_s = 0.1
    plugin.cmd_run({"freq": 40.0})
    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._poll_loop, args=(stop, pause), daemon=True)
    worker.start()
    for _ in range(200):
        if plugin._reg.running:
            break
        threading.Event().wait(0.005)
    stop.set()
    worker.join(timeout=2.0)
    assert plugin._reg.running is True
    assert plugin._reg.out_freq_hz == pytest.approx(40.0)
    assert plugin._reg.bridge_alive is True  # heartbeat растёт при пульсах
    ctx.state_proxy.merge.assert_called()
    path = ctx.state_proxy.merge.call_args.args[0]
    assert path == "vfd/status"
