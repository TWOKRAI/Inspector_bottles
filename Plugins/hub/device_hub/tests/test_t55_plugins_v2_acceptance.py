"""Слепая приёмка T5.5 (бриф T5.5t): плагины robot_draw и robot_io на роботе v2.

Purpose:
    Случаи B1-B6 из ``plans/robot-protocol-v2/tasks/T5.5.acceptance.md`` (ред. 2). Сквозные случаи (B1, B5) собирают
    настоящие объекты: ``RobotDrawPlugin`` / ``RobotIoPlugin`` -> мост ``_client`` -> команда ``DeviceHubPlugin`` ->
    настоящий ``RobotDriverV2`` -> sim v2 (``E2eRig``). Тик драйвера тест крутит сам (``pulse``): воркеры хаба на
    ``make_ctx`` - подделка. Источник требований - файл приёмки; реализация драйвера и плагинов не читалась.

Public API:
    Только тесты ``test_*``.

Stability: lite

Допущения теста (не из приёмки буквально):
    * B3: ``jobs_dropped`` плагина читается из ``plugin._reg`` (как ``jobs_sent`` в приёмке B1).
    * B4: «одинаковый текст без значений» - текст отказа не зависит от значения (``pen`` 2 и 7 дают один текст) и не
      содержит значений аргументов; текст пустого списка и текст ``pen`` между собой не сравниваются.
    * Дом sim - литерал приёмки; «done» программы - последняя публикация ``devices.state.r1.program``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Plugins.hub.device_hub.tests.test_robot_v2_commands_acceptance import _add_v2, _cmd, _plugin, _shutdown
from Plugins.io.robot_draw.plugin import RobotDrawPlugin
from Plugins.io.robot_io.plugin import RobotIoPlugin
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse

pytestmark = pytest.mark.timeout(150)

_CONNECT_S = 60.0
_DONE_S = 60.0
_STEP_S = 20.0
_TICK_PERIOD_S = 0.05

PROGRAM_PATH = "devices.state.r1.program"
HOME = (300.0, -210.0, -40.0, -100.0)
PEN_DOWN_MAX_Z = -49.9  # перо на листе: Z <= -49.9 (лист -50.0)
PEN_UP_MIN_Z = -40.5  # перо над листом: Z >= -40.5 (над листом -40.0)
TEXT_OUT_OF_ZONE = "вне зоны"
TEXT_UNKNOWN_OP = "Неизвестная операция"

# Квадрат 20x20 мм внутри зоны sim, начало pen=0 (приёмка: (300, 0)-(320, 20) внутри)
SQUARE = [
    {"x_mm": 300.0, "y_mm": 0.0, "pen": 0},
    {"x_mm": 320.0, "y_mm": 0.0, "pen": 1},
    {"x_mm": 320.0, "y_mm": 20.0, "pen": 1},
    {"x_mm": 300.0, "y_mm": 20.0, "pen": 1},
    {"x_mm": 300.0, "y_mm": 0.0, "pen": 1},
]

# Две «буквы» внутри того же квадрата; между ними точка pen=0 (перо уходит с листа)
TWO_STROKES = [
    {"x_mm": 300.0, "y_mm": 0.0, "pen": 0},
    {"x_mm": 300.0, "y_mm": 20.0, "pen": 1},
    {"x_mm": 310.0, "y_mm": 20.0, "pen": 1},
    {"x_mm": 310.0, "y_mm": 0.0, "pen": 0},
    {"x_mm": 320.0, "y_mm": 0.0, "pen": 1},
    {"x_mm": 320.0, "y_mm": 20.0, "pen": 1},
]


# --------------------------------------------------------------------------------------------------
# Обвязка
# --------------------------------------------------------------------------------------------------


@dataclass
class Stand:
    """Хаб + настоящий драйвер v2 + sim: то, что нужно случаям."""

    plugin: DeviceHubPlugin
    ctx: Any
    rig: E2eRig
    drv: Any


@pytest.fixture
def stand(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Stand]:
    """Хаб с роботом ``r1`` (delta_v2), подключённым к sim; тик драйвера тест крутит сам."""
    plugin, ctx = _plugin(tmp_path, monkeypatch)
    with E2eRig() as rig:
        try:
            _add_v2(plugin, "r1", rig.port)
            assert _cmd(plugin, "device_connect", {"device_id": "r1"})["status"] == "ok"
            bounded(plugin._process_conn_queue, _CONNECT_S)
            drv = plugin._manager.get_driver("r1")
            assert drv.is_connected, "обвязка: драйвер r1 не подключился к sim"
            yield Stand(plugin, ctx, rig, drv)
        finally:
            _shutdown(plugin, ctx)


class HubBridge:
    """Мост ``_client`` плагина в команду хаба в том же процессе; пишет вызовы и ответы."""

    def __init__(self, hub: DeviceHubPlugin) -> None:
        self._hub = hub
        self.calls: list[tuple[str, dict]] = []
        self.replies: list[dict] = []

    def request(self, command: str, args: dict | None = None, timeout: float | None = None) -> dict:
        data = dict(args or {})
        reply = _cmd(self._hub, command, data)
        self.calls.append((command, data))
        self.replies.append(reply)
        return reply


def _plugin_ctx(config: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.config = config
    ctx.registers = None
    ctx.state_proxy = MagicMock()
    ctx.worker_manager.create_worker = MagicMock()
    return ctx


def _make_draw(bridge: HubBridge) -> tuple[RobotDrawPlugin, MagicMock]:
    plugin = RobotDrawPlugin()
    ctx = _plugin_ctx({"device_id": "r1"})
    plugin.configure(ctx)
    with patch("Plugins.io.robot_draw.plugin.DeviceHubClient", return_value=bridge):
        plugin.start(ctx)
    plugin._client = bridge
    return plugin, ctx


def _make_io(bridge: HubBridge) -> tuple[RobotIoPlugin, MagicMock]:
    plugin = RobotIoPlugin()
    ctx = _plugin_ctx({"device_id": "r1"})
    plugin.configure(ctx)
    with patch("Plugins.io.robot_io.plugin.DeviceHubClient", return_value=bridge):
        plugin.start(ctx)
    plugin._client = bridge
    return plugin, ctx


@contextmanager
def _forwarding(plugin: Any) -> Iterator[None]:
    """Цикл форвардера плагина в daemon-потоке; выход: стоп-флаг и ``join`` с дедлайном."""
    stop = threading.Event()
    pause = threading.Event()
    worker = threading.Thread(target=plugin._forwarder_loop, args=(stop, pause), daemon=True, name="t55-forwarder")
    worker.start()
    try:
        yield
    finally:
        stop.set()
        worker.join(timeout=5.0)
        assert not worker.is_alive(), "форвардер плагина не остановился за 5 с"


def _wait(pred: Callable[[], bool], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while not pred():
        assert time.monotonic() < end, f"не дождались: {what} (дедлайн {deadline_s} с)"
        time.sleep(0.02)


def _program_states(ctx: Any) -> list[dict]:
    """Публикации ``devices.state.r1.program`` (копии), по порядку."""
    states: list[dict] = []
    for call in list(ctx.state_proxy.merge.call_args_list):
        if call.args and call.args[0] == PROGRAM_PATH:
            states.append(dict(call.args[1]))
    return states


def _program_final(ctx: Any, deadline_s: float = _DONE_S) -> dict:
    """Дождаться ``state`` в (done, error) последней публикации ``.program``; вернуть её."""
    last: dict = {}

    def settled() -> bool:
        nonlocal last
        states = _program_states(ctx)
        last = states[-1] if states else {}
        return last.get("state") in ("done", "error")

    _wait(settled, deadline_s, f".program дошла до done/error; публикации: {_program_states(ctx)}")
    return last


def _arm_and_send(plugin: RobotDrawPlugin, points: list[dict]) -> None:
    resp = plugin.cmd_send({})
    assert resp["status"] == "ok" and resp["armed"] is True, resp
    plugin.process([{"draw_points": [dict(p) for p in points]}])


# --------------------------------------------------------------------------------------------------
# B1: сквозной рисунок из плагина
# --------------------------------------------------------------------------------------------------


def test_b1_draw_plugin_to_hub_to_driver_v2_program_done(stand: Stand) -> None:
    """B1: плагин -> мост -> хаб -> драйвер v2 -> sim; ``.program`` = draw/done, done == total > 0."""
    bridge = HubBridge(stand.plugin)
    draw, draw_ctx = _make_draw(bridge)
    try:
        with pulse(stand.drv.tick, _TICK_PERIOD_S) as ticks:
            _arm_and_send(draw, SQUARE)
            with _forwarding(draw):
                _wait(lambda: len(bridge.replies) >= 1, _STEP_S, "хаб ответил на robot_draw_polyline")
                assert bridge.replies[0]["status"] == "ok", bridge.replies[0]
                _wait(lambda: draw._reg.jobs_sent >= 1, _STEP_S, "плагин отправил задание (jobs_sent >= 1)")
                final = _program_final(stand.ctx)
            assert ticks.errors == [], ticks.errors
        assert [c[0] for c in bridge.calls] == ["robot_draw_polyline"], bridge.calls
        assert bridge.replies[0]["status"] == "ok", bridge.replies[0]
        assert final["name"] == "draw", final
        assert final["state"] == "done", final
        assert final["done"] == final["total"], final
        assert final["total"] > 0, final
        assert draw._reg.jobs_sent == 1
    finally:
        draw.shutdown(draw_ctx)


# --------------------------------------------------------------------------------------------------
# B2: два штриха, дом и подъём пера
# --------------------------------------------------------------------------------------------------


def _run_two_strokes(stand: Stand) -> dict:
    assert stand.rig.pose_wire() == pytest.approx(HOME, abs=0.1), "обвязка: sim стартует не в доме"
    with pulse(stand.drv.tick, _TICK_PERIOD_S) as ticks:
        reply = _cmd(stand.plugin, "robot_draw_polyline", {"device_id": "r1", "points": [dict(p) for p in TWO_STROKES]})
        assert reply["status"] == "ok", reply
        final = _program_final(stand.ctx)
        assert ticks.errors == [], ticks.errors
    assert final["state"] == "done", final
    return final


def test_b2_two_strokes_program_done_and_robot_ends_at_home(stand: Stand) -> None:
    """B2(а): программа из двух штрихов доходит до ``done``; поза sim в конце - дом (300, -210, -40, -100) +-0.1."""
    final = _run_two_strokes(stand)
    assert final["name"] == "draw", final
    assert final["done"] == final["total"] > 0, final
    _wait(lambda: stand.rig.read("TLM_MOVING") == [0], _STEP_S, "sim остановился (TLM_MOVING == 0)")
    assert stand.rig.pose_wire() == pytest.approx(HOME, abs=0.1)


def test_b2_pen_lifts_between_strokes(stand: Stand) -> None:
    """B2(б): между первым и последним тиком с Z <= -49.9 есть тик с Z >= -40.5 (перо уходит с листа между буквами)."""
    _run_two_strokes(stand)
    zs = [tick.pose[2] for tick in stand.rig.core.ticks()]
    down = [i for i, z in enumerate(zs) if z <= PEN_DOWN_MAX_Z]
    assert down, f"перо ни разу не опускалось на лист (Z <= {PEN_DOWN_MAX_Z}); Z по тикам: min={min(zs)}"
    between = zs[down[0] : down[-1] + 1]
    assert any(z >= PEN_UP_MIN_Z for z in between), (
        f"между штрихами перо не поднялось: max Z между первым и последним касанием = {max(between)}"
    )


# --------------------------------------------------------------------------------------------------
# B3: точка вне зоны
# --------------------------------------------------------------------------------------------------


def test_b3_point_outside_zone_refused_via_plugin(stand: Stand) -> None:
    """B3: точка (0, 0) вне зоны -> ``status: error`` с «вне зоны»; ``.program`` нет; ``jobs_dropped`` плагина +1."""
    bridge = HubBridge(stand.plugin)
    draw, draw_ctx = _make_draw(bridge)
    try:
        dropped_before = draw._reg.jobs_dropped
        with pulse(stand.drv.tick, _TICK_PERIOD_S):
            _arm_and_send(draw, [{"x_mm": 0.0, "y_mm": 0.0, "pen": 0}, {"x_mm": 0.0, "y_mm": 0.0, "pen": 1}])
            with _forwarding(draw):
                _wait(lambda: len(bridge.replies) >= 1, _STEP_S, "хаб ответил на robot_draw_polyline")
                _wait(lambda: draw._reg.hub_errors >= 1, _STEP_S, "плагин принял отказ хаба (hub_errors >= 1)")
            time.sleep(0.5)  # публикация .program, если бы она была, успела бы появиться
        reply = bridge.replies[0]
        assert bridge.calls[0][0] == "robot_draw_polyline", bridge.calls
        assert reply["status"] == "error", reply
        assert TEXT_OUT_OF_ZONE in reply["message"], reply
        assert _program_states(stand.ctx) == []
        assert draw._reg.jobs_dropped == dropped_before + 1
    finally:
        draw.shutdown(draw_ctx)


def test_b3_point_outside_zone_refused_by_hub_command(stand: Stand) -> None:
    """B3 (команда хаба напрямую): ``status: error``, «вне зоны», ``.program`` не появляется."""
    with pulse(stand.drv.tick, _TICK_PERIOD_S):
        reply = _cmd(
            stand.plugin, "robot_draw_polyline", {"device_id": "r1", "points": [{"x_mm": 0.0, "y_mm": 0.0, "pen": 0}]}
        )
        time.sleep(0.5)
    assert reply["status"] == "error", reply
    assert TEXT_OUT_OF_ZONE in reply["message"], reply
    assert _program_states(stand.ctx) == []


# --------------------------------------------------------------------------------------------------
# B4: пустой список / pen = 2, и валидный вызов в том же тесте
# --------------------------------------------------------------------------------------------------


def test_b4_bad_arguments_refused_with_constant_text_and_valid_call_ok(stand: Stand) -> None:
    """B4: пустой список и ``pen = 2`` -> ``error`` с постоянным текстом без значений; квадрат -> ``ok`` и ``done``."""
    with pulse(stand.drv.tick, _TICK_PERIOD_S) as ticks:
        empty = _cmd(stand.plugin, "robot_draw_polyline", {"device_id": "r1", "points": []})
        bad_pen = _cmd(
            stand.plugin,
            "robot_draw_polyline",
            {"device_id": "r1", "points": [{"x_mm": 311.25, "y_mm": 7.5, "pen": 2}]},
        )
        bad_pen_other = _cmd(
            stand.plugin,
            "robot_draw_polyline",
            {"device_id": "r1", "points": [{"x_mm": 305.5, "y_mm": 3.75, "pen": 7}]},
        )
        for name, reply in (("empty", empty), ("pen=2", bad_pen), ("pen=7", bad_pen_other)):
            assert reply["status"] == "error", (name, reply)
            assert TEXT_UNKNOWN_OP not in reply["message"], (name, reply)
        assert bad_pen["message"] == bad_pen_other["message"], (bad_pen, bad_pen_other)
        for value in ("311.25", "7.5", "305.5", "3.75"):
            assert value not in bad_pen["message"] + bad_pen_other["message"], (bad_pen, bad_pen_other)
        assert _program_states(stand.ctx) == [], "отказ не должен порождать .program"

        valid = _cmd(stand.plugin, "robot_draw_polyline", {"device_id": "r1", "points": [dict(p) for p in SQUARE]})
        assert valid["status"] == "ok", valid
        final = _program_final(stand.ctx)
        assert ticks.errors == [], ticks.errors
    assert final["state"] == "done", final


# --------------------------------------------------------------------------------------------------
# B5: подача (robot_io) на v2
# --------------------------------------------------------------------------------------------------


def test_b5_feed_job_from_io_plugin_reaches_driver_jobs_done(stand: Stand) -> None:
    """B5: ``RobotIoPlugin`` -> мост -> ``robot_enqueue_job`` -> драйвер v2: ``jobs_done`` +1, ``queue_len == 0``."""
    bridge = HubBridge(stand.plugin)
    io, io_ctx = _make_io(bridge)
    try:
        before = stand.drv.snapshot()
        job = {"pick_x_mm": 300.0, "pick_y_mm": -150.0, "place_x_mm": 320.0, "place_y_mm": -120.0}
        io.process([{"robot_job": job}])
        with pulse(stand.drv.tick, _TICK_PERIOD_S) as ticks:
            with _forwarding(io):
                _wait(lambda: len(bridge.calls) >= 1, _STEP_S, "в хаб ушёл robot_enqueue_job")
                _wait(
                    lambda: (
                        stand.drv.snapshot()["jobs_done"] >= before["jobs_done"] + 1
                        and stand.drv.snapshot()["queue_len"] == 0
                    ),
                    _DONE_S,
                    "драйвер выполнил задание (jobs_done +1, queue_len == 0)",
                )
            assert ticks.errors == [], ticks.errors
        assert [c[0] for c in bridge.calls] == ["robot_enqueue_job"], bridge.calls
        assert bridge.replies[0]["status"] == "ok", bridge.replies[0]
        after = stand.drv.snapshot()
        assert after["jobs_done"] == before["jobs_done"] + 1, (before, after)
        assert after["queue_len"] == 0, after
    finally:
        io.shutdown(io_ctx)


# --------------------------------------------------------------------------------------------------
# B6: v1 не задет
# --------------------------------------------------------------------------------------------------


def test_b6_v1_robot_draw_polyline_still_ok(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_transport: Any, robot_entry: Any
) -> None:
    """B6: на роботе v1 (фейк-транспорт conftest) ``robot_draw_polyline`` -> ``status: ok`` (как на ``main``)."""
    from Services.device_hub.drivers.robot_driver import RobotDriver

    plugin, ctx = _plugin(tmp_path, monkeypatch)
    try:
        plugin._manager.register_driver_factory(
            "robot", lambda entry, proto: RobotDriver(entry, proto, transport=fake_transport)
        )
        assert _cmd(plugin, "device_upsert", robot_entry.to_dict())["status"] == "ok"
        assert plugin._manager.connect(robot_entry.id) is True
        polyline = _cmd(
            plugin,
            "robot_draw_polyline",
            {"device_id": robot_entry.id, "points": [{"x_mm": 0, "y_mm": 0, "pen": 1}]},
        )
        assert polyline["status"] == "ok", polyline
    finally:
        _shutdown(plugin, ctx)
