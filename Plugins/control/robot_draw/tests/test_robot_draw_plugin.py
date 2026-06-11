"""Тесты RobotDrawPlugin — асинхронное рисование через очередь + worker."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from Plugins.control.robot_draw.plugin import RobotDrawPlugin, gen_rect

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
    client = RobotClient(RobotConfig(), transport=FakeRobotTransport())
    client.connect()
    runtime.set_client(client)
    return client


def make_plugin() -> tuple[RobotDrawPlugin, MagicMock]:
    plugin = RobotDrawPlugin()
    ctx = make_ctx()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, ctx


def run_worker_until(plugin: RobotDrawPlugin, predicate, timeout_s: float = 3.0) -> None:
    """Прогнать _draw_loop в потоке до выполнения условия."""
    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._draw_loop, args=(stop, pause), daemon=True)
    worker.start()
    deadline = threading.Event()
    for _ in range(int(timeout_s / 0.01)):
        if predicate():
            break
        deadline.wait(0.01)
    stop.set()
    worker.join(timeout=2.0)


# --- gen_rect (чистая геометрия) ---


def test_gen_rect_four_corners_closed() -> None:
    pts = gen_rect(0, 0, 10, 20)
    assert len(pts) == 6  # подвод(up) + перо вниз + 3 угла + замыкание
    assert pts[0].pen == 0 and pts[1].pen == 1
    assert (pts[-1].x_mm, pts[-1].y_mm) == (0, 0)  # замкнут на угол 1


# --- команды: мгновенный возврат ---


def test_draw_commands_return_immediately() -> None:
    """Команда кладёт задание и возвращается сразу — без ожидания робота."""
    plugin, _ctx = make_plugin()
    result = plugin.cmd_draw_circle({"cx": 10, "cy": 20, "r": 5})
    assert result == {"status": "ok", "queued": 1}
    assert plugin._reg.state == "idle"  # ещё не исполнялось


def test_command_validation() -> None:
    plugin, _ctx = make_plugin()
    assert plugin.cmd_draw_circle({"cx": "x"})["status"] == "error"
    assert plugin.cmd_draw_points({"points": []})["status"] == "error"
    assert plugin.cmd_draw_square({})["status"] == "error"


def test_pen_speed_overlap_settings() -> None:
    plugin, _ctx = make_plugin()
    assert plugin.cmd_set_pen({"down": -2.0, "up": 8.0})["status"] == "ok"
    assert plugin._reg.pen_down_mm == -2.0
    assert plugin.cmd_set_draw_speed({"pct": 250})["pct"] == 100  # кламп
    assert plugin.cmd_set_overlap({"mm": 2.0})["status"] == "ok"


# --- исполнение worker'ом ---


def test_worker_executes_circle() -> None:
    client = publish_robot()
    plugin, _ctx = make_plugin()
    plugin.cmd_draw_circle({"cx": 15, "cy": 25, "r": 7, "z": -1.0})
    run_worker_until(plugin, lambda: plugin._reg.state in ("done", "failed"))
    assert plugin._reg.state == "done"
    assert plugin._reg.draws_done == 1
    # режим переключён в draw, перо задано из z задания
    assert client.read_registers(0x1109, 1) == [1]  # REG_MODE = DRAW
    assert client.read_registers(0x1410, 1) == [(-10) & 0xFFFF]  # pen_down = z*10


def test_worker_executes_square_points() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    plugin.cmd_draw_square({"x1": 0, "y1": 0, "x2": 10, "y2": 10})
    run_worker_until(plugin, lambda: plugin._reg.state in ("done", "failed"))
    assert plugin._reg.state == "done"
    assert plugin._reg.total_points == 6


def test_worker_fails_without_owner() -> None:
    plugin, _ctx = make_plugin()
    plugin.cmd_draw_circle({"cx": 1, "cy": 1, "r": 1})
    run_worker_until(plugin, lambda: plugin._reg.state == "failed")
    assert plugin._reg.state == "failed"
    assert "robot_io" in plugin._reg.last_error


def test_abort_draw_drops_queue() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    plugin.cmd_draw_circle({"cx": 1, "cy": 1, "r": 1})
    plugin.cmd_draw_circle({"cx": 2, "cy": 2, "r": 2})
    result = plugin.cmd_abort_draw({})
    assert result["status"] == "ok"
    assert result["dropped_tasks"] == 2


def test_process_auto_draw_disabled_by_default() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    items = [{"points": [{"x_mm": 1, "y_mm": 2, "pen": 1}]}]
    plugin.process(items)
    assert plugin._tasks.qsize() == 0  # auto_draw=False — безопасный дефолт


def test_process_auto_draw_enqueues_when_enabled() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    plugin._reg.auto_draw = True
    plugin.process([{"points": [{"x_mm": 1, "y_mm": 2, "pen": 1}]}])
    assert plugin._tasks.qsize() == 1


def test_get_draw_progress_reads_live_state() -> None:
    publish_robot()
    plugin, _ctx = make_plugin()
    result = plugin.cmd_get_draw_progress({})
    assert result["status"] == "ok"
    assert "busy" in result and "progress_point" in result
