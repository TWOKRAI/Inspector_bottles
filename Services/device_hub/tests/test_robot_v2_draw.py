"""Тесты автора T5.5a: ``draw_polyline`` драйвера робота v2 (точки v1 -> штрихи -> генератор ``draw`` -> программа).

Purpose:
    Дополняют слепую приёмку T5.5 (``Plugins/hub/device_hub/tests/test_t55_plugins_v2_acceptance.py``) свойствами
    драйвера: деление на штрихи по ``pen``, постоянный текст отказа разбора аргументов, потолок точек, высоты и ``z``
    как у v1, дом в конце, запуск программой на sim v2 (счёт возвратов не растёт), отказ второго рисунка, отказ точки
    вне зоны без движения, общий ``OpSpec`` v1/v2 без ``executor``. Ожидаемые тексты и числа - литералы.

Public API:
    Только тесты ``test_*``.

Stability: lite

Допущения теста:
    * Шов R4 - публичное имя ``compile_program`` модуля ``programs`` драйвера (подмена записывает программу и точки,
      затем зовёт настоящую функцию); приватные имена драйвера тест не трогает (сторож
      ``test_no_private_driver_state``).
    * Дом в R4 - литерал sim (``HOME``), а не ``drv._home_point()``: приватное имя увеличило бы число швов сторожа.
    * Штрихи ``_draw_strokes`` импортируются внутри тела теста: до правки имени нет, сбор файла не должен падать.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from multiprocess_framework.modules.base_manager import open_scope

from Plugins.hub.device_hub.plugin import DeviceHubPlugin
from Services.device_hub import kinds, spi
from Services.device_hub.drivers.robot_driver import RobotDriver
from Services.device_hub.drivers.robot_driver_v2 import RobotDriverV2
from Services.device_hub.registry.entry import DeviceEntry
from Services.robot_comm.core.registers import ROBOT_UNIT_ID
from Services.robot_comm.programs import compile_program as real_compile_program
from Services.robot_comm.tests.e2e_rig_v2 import E2eRig, bounded, pulse

pytestmark = pytest.mark.timeout(120)

_CALL_S = 15.0
_CONNECT_S = 60.0
_DONE_S = 60.0
_TICK_PERIOD_S = 0.1
_SCOPE_BUDGET_S = 6.0
_DEV = "rv2"
_PATH = f"devices.state.{_DEV}.program"

TEXT_BAD_ARGS = "неверные точки рисунка"
TEXT_TOO_MANY = "слишком много точек в рисунке"
TEXT_BUSY = "робот занят программой"
TEXT_OUT_OF_ZONE = "вне зоны"
HOME = (300.0, -210.0, -40.0, -100.0)  # дом sim по умолчанию (X, Y, Z, RZ)

# Квадрат 10x10 мм внутри зоны sim: подвод pen=0, три стороны и возврат pen=1
SQUARE = [
    {"x_mm": 300.0, "y_mm": 0.0, "pen": 0},
    {"x_mm": 310.0, "y_mm": 0.0, "pen": 1},
    {"x_mm": 310.0, "y_mm": 10.0, "pen": 1},
    {"x_mm": 300.0, "y_mm": 10.0, "pen": 1},
    {"x_mm": 300.0, "y_mm": 0.0, "pen": 1},
]
OUT_OF_ZONE = [{"x_mm": 0.0, "y_mm": 0.0, "pen": 0}, {"x_mm": 1.0, "y_mm": 0.0, "pen": 1}]


# --------------------------------------------------------------------------------------------------
# Обвязка
# --------------------------------------------------------------------------------------------------


class _Rec:
    """Публикации драйвера: путь -> список значений."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[tuple[str, Any]] = []

    def __call__(self, path: str, payload: Any) -> None:
        with self._lock:
            self._items.append((path, payload))

    def at(self, path: str) -> list[Any]:
        with self._lock:
            return [payload for p, payload in self._items if p == path]


@pytest.fixture
def scope() -> Iterator[Any]:
    """Область потоков теста: драйвер без ``spawn`` потоков не запускает; выживших быть не должно."""
    sc = open_scope("rv2draw", budget_s=_SCOPE_BUDGET_S)
    try:
        yield sc
    finally:
        report = sc.close()
        assert list(report.survivors) == [], f"выжившие потоки области теста: {list(report.survivors)}"


def _entry(port: int = 1, **params: Any) -> DeviceEntry:
    return DeviceEntry(
        id=_DEV,
        name=_DEV,
        kind="robot",
        protocol="delta_v2",
        transport={"type": "tcp", "host": "127.0.0.1", "port": port, "unit_id": ROBOT_UNIT_ID},
        params=dict(params),
    )


@contextmanager
def _connected(scope: Any, rec: _Rec, port: int, **params: Any) -> Iterator[RobotDriverV2]:
    """Настоящий драйвер v2, подключённый к sim; тик крутит вызывающий (``pulse``)."""
    drv = RobotDriverV2(_entry(port, **params), None, publish=rec, spawn=scope.spawn)
    try:
        assert bounded(drv.connect, _CONNECT_S) is True
        drv.desired_connected = True
        yield drv
    finally:
        try:
            bounded(drv.disconnect, _CALL_S)
        except Exception:  # noqa: BLE001 - уборка не подменяет исключение теста
            pass


def _draw(drv: RobotDriverV2, points: Any, **extra: Any) -> dict:
    return bounded(lambda: drv.call("draw_polyline", {"points": points, **extra}), _CALL_S)


def _wait(pred: Callable[[], object], deadline_s: float, what: str) -> None:
    end = time.monotonic() + deadline_s
    while not pred():
        if time.monotonic() >= end:
            raise AssertionError(f"не дождались: {what}")
        time.sleep(0.02)


def _count_done(rec: _Rec) -> int:
    return sum(1 for p in rec.at(_PATH) if p["state"] == "done")


def _wait_done(rec: _Rec, n: int = 1) -> None:
    _wait(lambda: _count_done(rec) >= n, _DONE_S, f"состояние программы done x{n}")


def _wait_released(drv: RobotDriverV2) -> None:
    """Захват исполнителя снят: рисунок вне зоны перестал получать отказ «занято» (отказ компиляции)."""
    _wait(lambda: _draw(drv, OUT_OF_ZONE)["message"] != TEXT_BUSY, _DONE_S, "захват снят после done")


# --------------------------------------------------------------------------------------------------
# R1. Штрихи
# --------------------------------------------------------------------------------------------------


def test_draw_strokes_split_on_pen_up() -> None:
    """R1: каждая точка pen=0 начинает новый штрих; pen=1 дописывает в текущий; первая точка pen=1 начинает штрих."""
    from Services.device_hub.drivers.robot_driver_v2.programs import _draw_strokes

    points = [
        {"x_mm": 0.0, "y_mm": 0.0, "pen": 0},
        {"x_mm": 1.0, "y_mm": 0.0, "pen": 1},
        {"x_mm": 2.0, "y_mm": 0.0, "pen": 1},
        {"x_mm": 5.0, "y_mm": 5.0, "pen": 0},
        {"x_mm": 6.0, "y_mm": 5.0, "pen": 1},
    ]
    assert _draw_strokes(points) == [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)], [(5.0, 5.0), (6.0, 5.0)]]
    first_pen_down = [{"x_mm": 3.0, "y_mm": 4.0, "pen": 1}, {"x_mm": 4.0, "y_mm": 4.0, "pen": 1}]
    assert _draw_strokes(first_pen_down) == [[(3.0, 4.0), (4.0, 4.0)]]


# --------------------------------------------------------------------------------------------------
# R2, R3. Разбор аргументов и потолок (до любого обращения к роботу: драйвер без связи)
# --------------------------------------------------------------------------------------------------

_GOOD = {"x_mm": 300.0, "y_mm": 0.0, "pen": 1}


@pytest.mark.parametrize(
    ("args", "case"),
    [
        pytest.param({"points": []}, "empty", id="empty-list"),
        pytest.param({"points": [{**_GOOD, "x_mm": True}]}, "bool-x", id="bool-x"),
        pytest.param({"points": [{**_GOOD, "x_mm": float("nan")}]}, "nan-x", id="nan-x"),
        pytest.param({"points": [{**_GOOD, "x_mm": 10**400}]}, "huge-int-x", id="huge-int-x"),
        pytest.param({"points": [{**_GOOD, "pen": 2}]}, "pen-2", id="pen-2"),
        pytest.param({"points": [{**_GOOD, "pen": True}]}, "pen-bool", id="pen-bool"),
        pytest.param({"points": [{**_GOOD, "pen": 1.0}]}, "pen-float", id="pen-float"),
        pytest.param({"points": [_GOOD], "z": "1"}, "z-str", id="z-str"),
        pytest.param({"points": [_GOOD], "z": True}, "z-bool", id="z-bool"),
        pytest.param({"points": [{"y_mm": 1.0}]}, "no-x", id="no-x"),
        pytest.param({"points": [5]}, "not-dict", id="point-not-dict"),
        pytest.param({"points": "abc"}, "points-str", id="points-str"),
    ],
)
def test_draw_bad_args_constant_text(scope: Any, args: dict, case: str) -> None:
    """R2: любое нарушение разбора - постоянный текст без входных значений, поток исполнителя не запущен."""
    spawned: list[str] = []

    def spy_spawn(target: Any, *, name: str) -> Any:
        spawned.append(name)
        return scope.spawn(target, name=name)

    drv = RobotDriverV2(_entry(), None, publish=_Rec(), spawn=spy_spawn)
    reply = drv.call("draw_polyline", dict(args))
    assert reply == {"status": "error", "message": TEXT_BAD_ARGS}, case
    assert spawned == [], case


def test_draw_too_many_points(scope: Any) -> None:
    """R3: точек больше ``draw_max_points`` - отказ с постоянным текстом; ровно ``draw_max_points`` - не этот отказ."""
    spawned: list[str] = []

    def spy_spawn(target: Any, *, name: str) -> Any:
        spawned.append(name)
        return scope.spawn(target, name=name)

    drv = RobotDriverV2(_entry(draw_max_points=3), None, publish=_Rec(), spawn=spy_spawn)
    row = {"x_mm": 300.0, "y_mm": 0.0, "pen": 1}
    reply = drv.call("draw_polyline", {"points": [row, row, row, row]})
    assert reply == {"status": "error", "message": TEXT_TOO_MANY}
    edge = drv.call("draw_polyline", {"points": [row, row, row]})
    assert edge["message"] != TEXT_TOO_MANY  # дальше - допуск запуска (связи нет), а не потолок
    assert spawned == []


# --------------------------------------------------------------------------------------------------
# R4. Высоты v1, z, дом в конце
# --------------------------------------------------------------------------------------------------


def test_draw_uses_v1_heights_and_z(scope: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """R4: Z точек ``draw/*`` - {перо, переезд, подъём} = {-50, -40, -30}; с ``z=-45`` - {-45, -35, -25}; последний
    ход - JOINT в дом."""
    from Services.device_hub.drivers.robot_driver_v2 import programs as programs_mod

    seen: list[tuple[Any, dict]] = []

    def recording_compile(program: Any, points: Any, frames: Any, params: Any) -> Any:
        scenario = real_compile_program(program, points, frames, params)  # проба вне зоны бросает - не записывается
        seen.append((program, dict(points)))
        return scenario

    monkeypatch.setattr(programs_mod, "compile_program", recording_compile)
    rec = _Rec()
    with E2eRig() as rig, _connected(scope, rec, rig.port) as drv, pulse(lambda: drv.tick(None), _TICK_PERIOD_S):
        first = _draw(drv, SQUARE)
        assert first["status"] == "ok", first
        _wait_done(rec, 1)
        _wait_released(drv)
        second = _draw(drv, SQUARE, z=-45)
        assert second["status"] == "ok", second
        _wait_done(rec, 2)

    assert len(seen) == 2
    heights = []
    for program, points in seen:
        heights.append({p.z for name, p in points.items() if name.startswith("draw/")})
        last = program.steps[-1]
        assert (last.op, last.point, last.kind) == ("move", "home", "JOINT")
        home = points["home"]
        assert (home.x, home.y, home.z, home.rz) == pytest.approx(HOME)
    assert heights == [{-50.0, -40.0, -30.0}, {-45.0, -35.0, -25.0}]


def _draw_recorded(scope: Any, monkeypatch: pytest.MonkeyPatch, drawing: list[dict], **params: Any) -> tuple[Any, dict]:
    """Нарисовать на sim с ``entry.params`` = ``params``; вернуть ``(program, points)`` успешной компиляции."""
    from Services.device_hub.drivers.robot_driver_v2 import programs as programs_mod

    seen: list[tuple[Any, dict]] = []

    def recording_compile(program: Any, points: Any, frames: Any, wparams: Any) -> Any:
        scenario = real_compile_program(program, points, frames, wparams)  # проба вне зоны бросает - не пишется
        seen.append((program, dict(points)))
        return scenario

    monkeypatch.setattr(programs_mod, "compile_program", recording_compile)
    rec = _Rec()
    with (
        E2eRig() as rig,
        _connected(scope, rec, rig.port, **params) as drv,
        pulse(lambda: drv.tick(None), _TICK_PERIOD_S),
    ):
        reply = _draw(drv, drawing)
        assert reply["status"] == "ok", reply
        _wait_done(rec, 1)
        _wait_released(drv)
    assert len(seen) == 1
    return seen[0]


def _acts(program: Any) -> list[tuple[str, int]]:
    return [(step.act, step.value) for step in program.steps if step.op == "act"]


def _draw_z(points: dict) -> set[float]:
    return {p.z for name, p in points.items() if name.startswith("draw/")}


def test_draw_default_speeds_accel_and_rz(scope: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Умолчания v1: рисование SPEED_PCT 30, затем ACCEL 25000, переезд SPEED_PCT 100; RZ точек - RZ дома."""
    program, points = _draw_recorded(scope, monkeypatch, SQUARE)
    steps = program.steps
    # подвод JOINT над началом (перо вверх), скорость рисования, ускорение, опускание
    assert (steps[0].op, steps[0].kind, points[steps[0].point].z) == ("move", "JOINT", -40.0)
    assert [(steps[1].op, steps[1].act, steps[1].value), (steps[2].op, steps[2].act, steps[2].value)] == [
        ("act", "SPEED_PCT", 30),
        ("act", "ACCEL", 25000),
    ]
    assert (steps[3].op, steps[3].kind, points[steps[3].point].z) == ("move", "LINE", -50.0)
    # после штриха: скорость переезда, финальный подъём, дом
    assert (steps[-3].op, steps[-3].act, steps[-3].value) == ("act", "SPEED_PCT", 100)
    assert (steps[-2].op, steps[-2].kind, points[steps[-2].point].z) == ("move", "LINE", -30.0)
    assert _acts(program) == [("SPEED_PCT", 30), ("ACCEL", 25000), ("SPEED_PCT", 100)]
    assert {p.rz for name, p in points.items() if name.startswith("draw/")} == {HOME[3]}
    assert {p.hand for p in points.values()} == {points["home"].hand}


def test_draw_entry_params_override_heights_speeds_accel(scope: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ключи ``entry.params`` v1 меняют высоты, скорости и ускорение; опечатка в имени ключа вернула бы умолчание."""
    two_strokes = [
        {"x_mm": 300.0, "y_mm": 0.0, "pen": 0},
        {"x_mm": 310.0, "y_mm": 0.0, "pen": 1},
        {"x_mm": 300.0, "y_mm": 10.0, "pen": 0},
        {"x_mm": 310.0, "y_mm": 10.0, "pen": 1},
    ]
    program, points = _draw_recorded(
        scope,
        monkeypatch,
        two_strokes,
        pen_down_mm=-48,
        pen_up_mm=-38,
        lift_mm=5,
        draw_speed_pct=20,
        draw_travel_pct=80,
        draw_accel=20000,
    )
    assert _draw_z(points) == {-48.0, -38.0, -33.0}
    # рисование 20, ускорение 20000 (раз, в первом штрихе), переезд 80 между штрихами, рисование 20, переезд 80 в конце
    assert _acts(program) == [
        ("SPEED_PCT", 20),
        ("ACCEL", 20000),
        ("SPEED_PCT", 80),
        ("SPEED_PCT", 20),
        ("SPEED_PCT", 80),
    ]


# --------------------------------------------------------------------------------------------------
# R5-R7. Сквозь sim v2
# --------------------------------------------------------------------------------------------------


def test_draw_runs_as_program_on_sim(scope: Any) -> None:
    """R5: квадрат внутри зоны -> ``ok``, ``total > 0``; ``.program`` доходит до ``done``; счёт возвратов не растёт."""
    rec = _Rec()
    with E2eRig() as rig, _connected(scope, rec, rig.port) as drv, pulse(lambda: drv.tick(None), _TICK_PERIOD_S):
        before = (drv.snapshot()["returns_done"], drv.snapshot()["returns_failed"])
        reply = _draw(drv, SQUARE)
        assert reply["status"] == "ok", reply
        assert reply["name"] == "draw"
        assert reply["total"] > 0
        _wait_done(rec, 1)
        last = rec.at(_PATH)[-1]
        assert (last["name"], last["state"], last["done"], last["total"]) == (
            "draw",
            "done",
            reply["total"],
            reply["total"],
        )
        _wait_released(drv)  # program_finished идёт ПОСЛЕ публикации done: без этого проверка счётчика гоночная
        after = drv.snapshot()
        assert (after["returns_done"], after["returns_failed"]) == before


def test_draw_while_program_running_refused(scope: Any) -> None:
    """R6: второй рисунок, пока идёт первый, получает отказ допуска; первый доходит до ``done``."""
    rec = _Rec()
    with E2eRig() as rig, _connected(scope, rec, rig.port) as drv, pulse(lambda: drv.tick(None), _TICK_PERIOD_S):
        first = _draw(drv, SQUARE)
        assert first["status"] == "ok", first
        second = _draw(drv, SQUARE)
        assert second == {"status": "error", "message": TEXT_BUSY}
        _wait_done(rec, 1)
        assert rec.at(_PATH)[-1]["state"] == "done"


def test_draw_point_out_of_zone_refused_without_motion(scope: Any) -> None:
    """R7: точка (0, 0) вне зоны -> ошибка с «вне зоны»; программа не публикуется, поза sim не меняется."""
    rec = _Rec()
    with E2eRig() as rig, _connected(scope, rec, rig.port) as drv, pulse(lambda: drv.tick(None), _TICK_PERIOD_S):
        pose_before = rig.pose_wire()
        reply = _draw(drv, OUT_OF_ZONE)
        assert reply["status"] == "error"
        assert TEXT_OUT_OF_ZONE in reply["message"]
        time.sleep(0.5)  # окно для неверного движения: sim тикает по 0.01 с
        assert rec.at(_PATH) == []
        assert rig.pose_wire() == pytest.approx(pose_before, abs=0.1)
        assert pose_before == pytest.approx(HOME, abs=0.1), "обвязка: sim стартует не в доме"


# --------------------------------------------------------------------------------------------------
# R8. Общий OpSpec v1/v2 без executor
# --------------------------------------------------------------------------------------------------


def test_draw_polyline_shared_spec_without_executor() -> None:
    """R8: ``command_table`` строится для v1 и v2; ``draw_polyline`` - один объект в обоих каталогах, без
    ``executor`` и ``immediate``; команды с ``executor`` - прежние (10 операций данных и ``robot_park_all``)."""
    for cls in (RobotDriver, RobotDriverV2):
        source = spi.OpSource(prefix="robot", kind="robot", route="driver", ops=cls.OP_SPECS)
        assert "robot_draw_polyline" in spi.command_table([source])
    v1 = {s.name: s for s in RobotDriver.OP_SPECS}
    v2 = {s.name: s for s in RobotDriverV2.OP_SPECS}
    assert "draw_polyline" in v2
    assert v2["draw_polyline"] is v1["draw_polyline"]

    table = spi.command_table(kinds.DEFAULT_SOURCES)
    spec = table["robot_draw_polyline"][1]
    assert spec is v2["draw_polyline"]
    assert spec.executor is None
    assert spec.immediate is False

    plugin = DeviceHubPlugin()
    with_executor = sorted(n for n in DeviceHubPlugin.commands if plugin.command_options(n).get("executor"))
    assert with_executor == sorted(
        [
            f"robot_{op}"
            for op in (
                "param_get_all",
                "point_list",
                "point_save",
                "point_delete",
                "frame_list",
                "frame_teach",
                "program_list",
                "program_get",
                "program_save",
                "program_delete",
            )
        ]
        + ["robot_park_all"]
    )
