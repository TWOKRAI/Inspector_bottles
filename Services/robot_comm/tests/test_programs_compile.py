"""Тесты автора T3.3: опасности моделей программ и `compile_program`.

Purpose: закрепить то, что слепая приёмка (`test_programs_acceptance.py`) не держит: слияние действия
против дубль-записи, порядок отказов между шагами и внутри шага, валидацию моделей (NaN/inf, вырожденная
СК, чужая версия, имена и диапазоны действий), круг `to_dict` → `from_dict` каждого класса, коды 0 и 7,
текст ошибок без входных значений. Ожидаемые значения — литералы (protocol-spec §7), не из кода под тестом.
Public API: нет (только тесты); ``__all__`` пуст.
Stability: lite
"""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from Services.robot_comm.core import protocol_v2
from Services.robot_comm.programs import (
    Action,
    CompileError,
    FrameDef,
    Move,
    Point,
    Program,
    Record,
    Scenario,
    compile_program,
)

__all__: list[str] = []

PARAMS: dict[str, float] = {
    "P_WS_R_MIN": 100.0,
    "P_WS_R_MAX": 600.0,
    "P_WS_Z_MIN": -150.0,
    "P_WS_Z_MAX": 0.0,
    "P_WS_RZ_MIN": -360.0,
    "P_WS_RZ_MAX": 360.0,
    "P_WS_ANG_MIN": -165.0,
    "P_WS_ANG_MAX": 165.0,
    "P_WS_BOX_EN": 0.0,
    "P_WS_X_MIN": -600.0,
    "P_WS_X_MAX": 600.0,
    "P_WS_Y_MIN": -600.0,
    "P_WS_Y_MAX": 600.0,
    "P_HAND": 1.0,
}

# Точки в зоне (r 100..600, угол ±165, z -150..0): a→b и b→c — отрезки далеко от оси J1.
A = (400.0, 0.0, -50.0, 0.0)
B = (400.0, 100.0, -50.0, 10.0)
C = (300.0, 200.0, -60.0, 20.0)
NEAR, FAR = (200.0, 100.0, -50.0, 0.0), (-50.0, -150.0, -50.0, 0.0)  # прямая между ними — в 70.7 мм от оси
OUT = (800.0, 0.0, -50.0, 0.0)  # r = 800 > 600


def _pt(name: str, xyzr: tuple, hand: int = 1, frame: str | None = None) -> Point:
    x, y, z, rz = xyzr
    return Point(name=name, x=x, y=y, z=z, rz=rz, hand=hand, frame=frame)


def _compile(steps: list, points: dict, frames: dict | None = None) -> Scenario:
    return compile_program(Program(name="t", steps=tuple(steps)), points, frames or {}, PARAMS)


def _fail(steps: list, points: dict, frames: dict | None = None) -> CompileError:
    with pytest.raises(CompileError) as info:
        _compile(steps, points, frames)
    return info.value


def _rows(sc: Scenario) -> list[tuple]:
    return [(r.kind, r.action, r.aparam, k) for r, k in zip(sc.records, sc.step_of, strict=True)]


POINTS = {"a": _pt("a", A), "b": _pt("b", B), "c": _pt("c", C)}


# --- слияние против дубль-записи -----------------------------------------------------------------------------
def test_two_actions_after_one_point_merge_then_duplicate():
    sc = _compile(
        [Move(point="a", kind="JOINT"), Action(act="DO_ON", value=3), Action(act="DELAY_MS", value=250)], POINTS
    )
    assert _rows(sc) == [("JOINT", "DO_ON", 3, 0), ("LINE", "DELAY_MS", 250, 2)]
    assert (sc.records[1].x, sc.records[1].y, sc.records[1].z, sc.records[1].rz) == A


def test_action_after_line_pass_gives_duplicate_line():
    """О7: контроллер PASS-точку сглаживает — действие после неё не сливается, а даёт остановку LINE."""
    sc = _compile(
        [
            Move(point="a", kind="JOINT"),
            Move(point="b", kind="LINE_PASS"),
            Action(act="DO_OFF", value=16),
            Move(point="c", kind="LINE"),
        ],
        POINTS,
    )
    assert _rows(sc) == [
        ("JOINT", "NONE", 0, 0),
        ("LINE_PASS", "NONE", 0, 1),
        ("LINE", "DO_OFF", 16, 2),
        ("LINE", "NONE", 0, 3),
    ]
    assert (sc.records[2].x, sc.records[2].y, sc.records[2].z, sc.records[2].rz) == B


def test_action_after_last_line_merges_into_last_record():
    sc = _compile([Move(point="a", kind="JOINT"), Move(point="b", kind="LINE"), Action(act="ACCUR", value=1)], POINTS)
    assert _rows(sc) == [("JOINT", "NONE", 0, 0), ("LINE", "ACCUR", 1, 1)]


# --- порядок отказов -----------------------------------------------------------------------------------------
def test_earlier_step_error_wins():
    pts = {**POINTS, "out": _pt("out", OUT), "lefty": _pt("lefty", A, hand=0)}
    err = _fail(
        [Move(point="a", kind="JOINT"), Move(point="lefty", kind="JOINT"), Move(point="out", kind="JOINT")], pts
    )
    assert (err.step, err.reason) == (1, 7)
    err = _fail([Move(point="out", kind="JOINT"), Move(point="nope", kind="JOINT")], pts)
    assert (err.step, err.reason) == (0, 4)


def test_last_line_pass_through_dead_zone_is_6_not_5():
    pts = {"n": _pt("n", NEAR), "f": _pt("f", FAR)}
    err = _fail([Move(point="n", kind="JOINT"), Move(point="f", kind="LINE_PASS")], pts)
    assert (err.step, err.reason) == (1, 6)


def test_mid_line_pass_through_dead_zone_is_5():
    pts = {"n": _pt("n", NEAR), "f": _pt("f", FAR), "c": _pt("c", (-100.0, -300.0, -50.0, 0.0))}
    err = _fail([Move(point="n", kind="JOINT"), Move(point="f", kind="LINE_PASS"), Move(point="c", kind="JOINT")], pts)
    assert (err.step, err.reason) == (1, 5)


def test_in_step_order_point_before_hand_before_segment():
    pts = {"n": _pt("n", NEAR), "out_l": _pt("out_l", OUT, hand=0), "far_l": _pt("far_l", FAR, hand=0)}
    assert _fail([Move(point="out_l", kind="JOINT")], pts).reason == 4  # вне зоны и чужая рука → 4
    err = _fail([Move(point="n", kind="JOINT"), Move(point="far_l", kind="LINE")], pts)
    assert (err.step, err.reason) == (1, 7)  # чужая рука и мёртвая зона → 7


def test_unknown_point_before_last_pass():
    err = _fail([Move(point="a", kind="JOINT"), Move(point="ghost", kind="LINE_PASS")], POINTS)
    assert (err.step, err.reason) == (1, 0)


def test_segment_leaving_sector_is_4():
    """Оба конца в зоне (углы ±160), отрезок далеко от оси, но через сектор |угол| > 165 → 4 на шаге отрезка."""
    p = (500 * math.cos(math.radians(160)), 500 * math.sin(math.radians(160)), -50.0, 0.0)
    q = (p[0], -p[1], -50.0, 0.0)
    err = _fail([Move(point="p", kind="JOINT"), Move(point="q", kind="LINE")], {"p": _pt("p", p), "q": _pt("q", q)})
    assert (err.step, err.reason) == (1, 4)


def test_first_line_record_has_no_segment_check():
    """О2: отрезок к первой записи не проверяется (поза при компиляции неизвестна)."""
    assert _rows(_compile([Move(point="a", kind="LINE")], POINTS)) == [("LINE", "NONE", 0, 0)]


# --- коды 0 и 7 ----------------------------------------------------------------------------------------------
def test_hand_differs_from_p_hand_is_7():
    err = _fail([Move(point="r", kind="JOINT")], {"r": _pt("r", A, hand=0)})
    assert (err.step, err.reason) == (0, 7)


def test_unknown_point_and_unknown_frame_are_0():
    err = _fail([Move(point="a", kind="JOINT"), Move(point="zz", kind="JOINT")], POINTS)
    assert (err.step, err.reason) == (1, 0)
    pts = {**POINTS, "f": _pt("f", (1.0, 2.0, 0.0, 0.0), frame="nowhere")}
    err = _fail([Move(point="a", kind="JOINT"), Move(point="f", kind="JOINT")], pts)
    assert (err.step, err.reason) == (1, 0)


def test_actions_only_and_empty_program_are_0():
    err = _fail([Action(act="DELAY_MS", value=1), Action(act="DO_ON", value=1)], {})
    assert (err.step, err.reason) == (0, 0)
    err = _fail([], {})
    assert (err.step, err.reason) == (0, 0)


def test_action_before_first_move_is_0_at_its_step():
    err = _fail([Action(act="DO_ON", value=2), Move(point="a", kind="JOINT")], POINTS)
    assert (err.step, err.reason) == (0, 0)


# --- текст ошибок без входных значений ---------------------------------------------------------------------
def test_compile_error_text_has_step_and_reason_text_not_inputs():
    err = _fail([Move(point="a", kind="JOINT"), Move(point="SECRET_NAME_42", kind="JOINT")], POINTS)
    assert "SECRET_NAME_42" not in str(err) and "1" in err.text
    err = _fail([Move(point="r", kind="JOINT")], {"r": _pt("r", (123.456789, 0.0, -50.0, 0.0), hand=0)})
    assert "чужая конфигурация руки" in err.text and "123.45" not in err.text
    assert isinstance(err, ValueError)


@pytest.mark.parametrize(
    ("factory", "secret"),
    [
        (lambda: Action(act="DELAY_MS", value=987654), "987654"),
        (lambda: Action(act="SECRET_ACT_42", value=1), "SECRET_ACT_42"),
        (lambda: Move(point="a", kind="SECRET_KIND_42"), "SECRET_KIND_42"),
        (lambda: Point(name="p", x=1.0, y=2.0, z=3.0, rz=4.0, hand=987654), "987654"),
        (lambda: Program(version=987654, name="p", steps=()), "987654"),
    ],
)
def test_validation_error_text_hides_input(factory, secret):
    with pytest.raises(ValidationError) as info:
        factory()
    assert secret not in str(info.value)


# --- валидация моделей ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", ["x", "y", "z", "rz"])
def test_point_rejects_non_finite(field, bad):
    kw = {"name": "p", "x": 1.0, "y": 2.0, "z": 3.0, "rz": 4.0, "hand": 1, field: bad}
    with pytest.raises(ValidationError):
        Point(**kw)


def test_point_rejects_hand_2_and_empty_name():
    with pytest.raises(ValidationError):
        _pt("p", A, hand=2)
    with pytest.raises(ValidationError):
        _pt("", A)


@pytest.mark.parametrize("hand", [True, False, 1.0, "1"])
def test_point_hand_must_be_strict_int(hand):
    """Точки из YAML, правленного руками: bool, float и строка не приводятся к руке молча."""
    with pytest.raises(ValidationError):
        _pt("p", A, hand=hand)


def _rec(**kw) -> Record:
    return Record(**{"x": 1.0, "y": 2.0, "z": 3.0, "rz": 4.0, "kind": "LINE", "action": "DO_ON", "aparam": 7, **kw})


@pytest.mark.parametrize("aparam", ["7", True, 7.0])
def test_record_aparam_must_be_strict_int(aparam):
    with pytest.raises(ValidationError):
        _rec(aparam=aparam)
    with pytest.raises(ValidationError):
        Scenario.from_dict({"records": [{**_rec().to_dict(), "aparam": aparam}], "step_of": [0]})


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", ["x", "y", "z", "rz"])
def test_record_rejects_non_finite(field, bad):
    with pytest.raises(ValidationError):
        _rec(**{field: bad})


@pytest.mark.parametrize(
    ("origin", "on_x", "in_plane", "phrase"),
    [
        ((0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 10.0, 0.0), "ось X не определена"),
        ((0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.5, 0.0), "плоскость не определена"),
    ],
)
def test_degenerate_frame_is_validation_error_with_geometry_text(origin, on_x, in_plane, phrase):
    with pytest.raises(ValidationError) as info:
        FrameDef(name="f", origin=origin, on_x=on_x, in_plane=in_plane)
    assert phrase in str(info.value)


def test_frame_rejects_nan_coordinate():
    with pytest.raises(ValidationError):
        FrameDef(name="f", origin=(0.0, 0.0, math.nan), on_x=(10.0, 0.0, 0.0), in_plane=(0.0, 10.0, 0.0))


@pytest.mark.parametrize("version", [2, 0, True, "1"])
def test_foreign_version_rejected_with_clear_text(version):
    with pytest.raises(ValidationError) as info:
        Program(version=version, name="p", steps=())
    assert "версия формата программы не поддерживается" in str(info.value)


def test_constructors_are_keyword_only():
    with pytest.raises(TypeError):
        Move("a", "LINE")  # type: ignore[misc]


@pytest.mark.parametrize("kind", ["LIN", "line", "NONE", 0, 2])
def test_unknown_kind_rejected(kind):
    with pytest.raises(ValidationError):
        Move(point="a", kind=kind)


@pytest.mark.parametrize("act", ["NONE", "DO", "do_on", 1, 3])
def test_unknown_act_rejected(act):
    with pytest.raises(ValidationError):
        Action(act=act, value=1)


@pytest.mark.parametrize("value", [True, False, "7", 7.0])
def test_action_value_must_be_strict_int(value):
    with pytest.raises(ValidationError):
        Action(act="DO_ON", value=value)


# Границы таблицы — литералы protocol-spec §7.2 / метаданных P_ACC_L (100..50000 мм/с²).
RANGES = {
    "DO_ON": (1, 16),
    "DO_OFF": (1, 16),
    "DELAY_MS": (0, 65535),
    "SPEED_PCT": (1, 100),
    "ACCEL": (100, 50000),
    "ACCUR": (0, 1),
}


@pytest.mark.parametrize("act", sorted(RANGES))
def test_action_range_boundaries(act):
    lo, hi = RANGES[act]
    assert Action(act=act, value=lo).value == lo
    assert Action(act=act, value=hi).value == hi
    for bad in (lo - 1, hi + 1):
        with pytest.raises(ValidationError):
            Action(act=act, value=bad)


def test_every_act_name_has_a_range():
    """Каждое имя ACT, кроме NONE, — в литеральной таблице; новое имя codegen увидит этот тест."""
    assert set(protocol_v2.ACT) - {"NONE"} == set(RANGES)


def test_new_act_without_range_is_validation_error(monkeypatch):
    monkeypatch.setitem(protocol_v2.ACT, "NEW_ACT", 99)
    with pytest.raises(ValidationError) as info:
        Action(act="NEW_ACT", value=0)
    assert "нет диапазона" in str(info.value)


def test_scenario_length_mismatch_rejected():
    rec = Record(x=1.0, y=2.0, z=3.0, rz=4.0, kind="LINE", action="NONE", aparam=0)
    with pytest.raises(ValidationError):
        Scenario(records=(rec,), step_of=(0, 1))


# --- круг to_dict → from_dict --------------------------------------------------------------------------------
FRAME = FrameDef(name="f", origin=(300.0, 0.0, -50.0), on_x=(300.0, 100.0, -50.0), in_plane=(200.0, 0.0, -50.0))


@pytest.mark.parametrize(
    "obj",
    [
        _pt("p", A, frame="f"),
        FRAME,
        Move(point="a", kind="LINE_PASS"),
        Action(act="ACCEL", value=25000),
        Program(name="p", steps=(Move(point="a", kind="JOINT"), Action(act="DO_ON", value=5))),
        Record(x=1.5, y=-2.5, z=-3.0, rz=4.25, kind="JOINT", action="SPEED_PCT", aparam=50),
        Scenario(records=(Record(x=1.0, y=2.0, z=3.0, rz=4.0, kind="LINE", action="NONE", aparam=0),), step_of=(0,)),
    ],
    ids=lambda o: type(o).__name__,
)
def test_to_dict_from_dict_roundtrip(obj):
    d = obj.to_dict()
    back = type(obj).from_dict(d)
    assert back == obj
    assert back.to_dict() == d


def test_to_dict_names_are_strings():
    d = Program(name="p", steps=(Move(point="a", kind="JOINT"), Action(act="DO_ON", value=5))).to_dict()
    assert d == {
        "version": 1,
        "name": "p",
        "steps": [{"op": "move", "point": "a", "kind": "JOINT"}, {"op": "act", "act": "DO_ON", "value": 5}],
    }


def test_frame_from_dict_rebuilds_geometry():
    back = FrameDef.from_dict(FRAME.to_dict())
    assert back.to_base(10.0, 20.0, 0.0, 5.0) == pytest.approx((280.0, 10.0, -50.0, 95.0), abs=1e-9)


# --- СК и прочее ---------------------------------------------------------------------------------------------
def test_point_in_frame_compiles_to_base():
    """СК: начало (300, 0, -50), ось X вдоль +Y базы (yaw 90°), третья точка со стороны −Y СК."""
    sc = _compile([Move(point="p", kind="JOINT")], {"p": _pt("p", (10.0, 20.0, 0.0, 5.0), frame="f")}, {"f": FRAME})
    rec = sc.records[0]
    assert (rec.x, rec.y, rec.z, rec.rz) == pytest.approx((280.0, 10.0, -50.0, 95.0), abs=1e-9)


def test_long_program_not_cut_by_sc_cap():
    """Длина сценария не режется по SC_CAP = 55 (резка — клиент, §7.4)."""
    steps = [Move(point="a" if i % 2 == 0 else "b", kind="LINE") for i in range(60)]
    sc = _compile(steps, POINTS)
    assert len(sc.records) == 60 and list(sc.step_of) == list(range(60))


def test_compile_is_pure():
    prog = Program(
        name="p", steps=(Move(point="a", kind="JOINT"), Action(act="DO_ON", value=1), Action(act="DO_OFF", value=1))
    )
    first = compile_program(prog, POINTS, {}, PARAMS)
    second = compile_program(prog, POINTS, {}, PARAMS)
    assert first == second and len(first.records) == 2
