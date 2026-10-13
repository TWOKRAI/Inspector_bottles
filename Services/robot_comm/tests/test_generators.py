"""Тесты автора T3.4: генераторы программ робота (`Services.robot_comm.programs.generators`).

Purpose: закрепить то, что слепая приёмка (`test_generators_acceptance.py`) не видит: связь правила 26 с
буфером пинг-понга (`wire_v2.plan_chunks`, `SC_CAP`), инварианты сборщика `_Builder`, несхлопывание
`approach`/`home`, краевые штрихи, ошибки аргументов, сдвиг `return_slot` в повёрнутой СК, точный текст
ошибок `toolchange`, замкнутость `GeneratedProgram.points`.
Public API: нет (только тесты); ``__all__`` пуст.
Stability: lite

Ожидаемые значения — литералы (мм, °), посчитанные вручную по DESIGN брифа T3.4, не по коду генераторов.
"""

from __future__ import annotations

import inspect

import pytest

from Services.robot_comm.core.protocol_v2 import CONSTANTS
from Services.robot_comm.core.wire_v2 import plan_chunks
from Services.robot_comm.programs import Action, CompileError, FrameDef, Move, Point, compile_program
from Services.robot_comm.programs.generators import (
    GeneratedProgram,
    GeneratorError,
    circle_stroke,
    draw,
    return_slot,
    square_stroke,
    toolchange,
)
from Services.robot_comm.programs.generators._common import _Builder

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
SHEET = FrameDef(name="sheet", origin=(300, -100, -100), on_x=(400, -100, -100), in_plane=(300, 0, -100))
FRAMES = {"sheet": SHEET}
HOME = Point(name="home", x=300, y=-210, z=-40, rz=-100, hand=1)
LIB = {
    name: Point(name=name, x=x, y=y, z=z, rz=0, hand=1)
    for name, (x, y, z) in {
        "t1_over": (400, 100, -20),
        "t1_pick": (400, 100, -80),
        "t1_exit": (400, 160, -80),
        "t2_over": (400, -100, -20),
        "t2_pick": (400, -100, -80),
        "t2_exit": (400, -40, -80),
    }.items()
}
SLOT = Point(name="slot", x=350, y=-150, z=-90, rz=10, hand=1)
LI = (
    ((0, 0), (8, 40), (25, 40), (25, 0)),
    ((35, 40), (35, 0), (55, 40)),
    ((55, 40), (55, 0)),
)
PEN = {"frame": "sheet", "hand": 1, "rz": 0.0, "pen_down": 0.0, "pen_up": 5.0}
LONG = tuple((0.5 * j, 20.0) for j in range(100))


def _compile(gp: GeneratedProgram, frames: dict | None = None):
    return compile_program(gp.program, gp.points, FRAMES if frames is None else frames, PARAMS)


def _rows(gp: GeneratedProgram, frames: dict | None = None) -> list[tuple]:
    return [(r.x, r.y, r.z, r.rz, r.kind, r.action, r.aparam) for r in _compile(gp, frames).records]


def _moves(gp: GeneratedProgram) -> list[Move]:
    return [s for s in gp.program.steps if isinstance(s, Move)]


def _longest_pass_run(kinds: list[str]) -> int:
    best = run = 0
    for kind in kinds:
        run = run + 1 if kind == "LINE_PASS" else 0
        best = max(best, run)
    return best


def _all_generated() -> dict[str, GeneratedProgram]:
    """Каждый генератор без и с `home` (для свойств, общих для всех трёх)."""
    out: dict[str, GeneratedProgram] = {}
    for suffix, extra in (("", {}), ("+home", {"home": HOME})):
        out["draw" + suffix] = draw(LI, **PEN, **extra)
        out["return_slot" + suffix] = return_slot(SLOT, **extra)
        out["toolchange" + suffix] = toolchange(1, 2, LIB, **extra)
        # 0→1 берёт 3 точки из 6 библиотеки — без него «только точки ходов» у toolchange не проверялось (инъекция I18)
        out["toolchange_0_1" + suffix] = toolchange(0, 1, LIB, **extra)
    return out


def test_pass_run_capped_and_chunks_plan() -> None:
    """Правило 26 держит нарезку пинг-понга: ряд 26 режется на куски, ряд 27 — уже нет (граница доказана)."""
    half = CONSTANTS["SC_CAP"] // 2
    for strokes in ((LONG,), (circle_stroke(30, 20, 15, segments=64),)):
        scenario = _compile(draw(strokes, **PEN))
        kinds = [r.kind for r in scenario.records]
        assert _longest_pass_run(kinds) == 26
        plan_chunks(kinds, half, scenario.step_of)  # не бросает
    scenario = _compile(draw((LONG,), **PEN, max_pass_run=27))
    kinds = [r.kind for r in scenario.records]
    assert _longest_pass_run(kinds) == 27
    with pytest.raises(CompileError):
        plan_chunks(kinds, half, scenario.step_of)


def test_default_max_pass_run_is_half_buffer_minus_one() -> None:
    """Умолчание `max_pass_run` связано с буфером прошивки: `SC_CAP // 2 - 1` (при SC_CAP 55 — 26)."""
    default = inspect.signature(draw).parameters["max_pass_run"].default
    assert default == CONSTANTS["SC_CAP"] // 2 - 1
    assert default == 26


def test_actions_only_after_exact_moves() -> None:
    """Действия — только после EXACT-ходов; `_Builder.build()` ловит нарушения сам."""
    for label, gp in _all_generated().items():
        steps = gp.program.steps
        first_move = next(i for i, s in enumerate(steps) if isinstance(s, Move))
        assert not any(isinstance(s, Action) for s in steps[:first_move]), label
        last_move: Move | None = None
        for step in steps:
            if isinstance(step, Move):
                last_move = step
            else:
                assert last_move is not None and last_move.kind != "LINE_PASS", label
        rows = _rows(gp)
        for a, b in zip(rows, rows[1:], strict=False):
            assert not (a[4] == "LINE_PASS" and a[:3] == b[:3]), f"{label}: дубль-запись после LINE_PASS"

    def built(*ops) -> None:
        b = _Builder("t")
        for op in ops:
            op(b)
        b.build()

    def new(kind: str):
        return lambda b: b.move_new(300, 0, -50, 0, hand=1, frame=None, kind=kind)

    def act(b: _Builder) -> None:
        b.act("DELAY_MS", 1)

    built(new("JOINT"), new("LINE"), act)  # штатная программа собирается
    with pytest.raises(GeneratorError):
        built(new("LINE"), new("LINE"))  # первый ход не JOINT
    with pytest.raises(GeneratorError):
        built(act, new("JOINT"))  # действие первым шагом
    with pytest.raises(GeneratorError):
        built(new("JOINT"), new("LINE_PASS"))  # последний ход LINE_PASS
    with pytest.raises(GeneratorError):
        built(new("JOINT"), new("LINE_PASS"), act, new("LINE"))  # действие после LINE_PASS


def test_first_move_joint_last_move_not_pass() -> None:
    """Первый ход JOINT, последний не LINE_PASS; `home` — последним JOINT, `approach` — первым; не схлопываются."""
    for label, gp in _all_generated().items():
        moves = _moves(gp)
        assert moves[0].kind == "JOINT", label
        assert moves[-1].kind != "LINE_PASS", label
        if label.endswith("+home"):
            assert (moves[-1].point, moves[-1].kind) == ("home", "JOINT"), label
    for label, gp in (
        ("return_slot", return_slot(SLOT, approach=HOME)),
        ("toolchange", toolchange(1, 2, LIB, approach=HOME)),
    ):
        moves = _moves(gp)
        assert (moves[0].point, moves[0].kind) == ("home", "JOINT"), label
        assert moves[1].kind == "LINE", label
        assert all(m.kind == "LINE" for m in moves[1:]), label

    # approach == первая точка маршрута (имя и координаты): не схлопывается.
    gp = toolchange(1, 2, LIB, approach=LIB["t1_exit"])
    assert [(m.point, m.kind) for m in _moves(gp)[:2]] == [("t1_exit", "JOINT"), ("t1_exit", "LINE")]
    assert len(_moves(gp)) == 7
    over = Point(name="return_slot/0", x=350, y=-150, z=-70, rz=10, hand=1)  # та же точка, что «над слотом»
    gp = return_slot(SLOT, approach=over)
    assert [(m.point, m.kind) for m in _moves(gp)[:2]] == [("return_slot/0", "JOINT"), ("return_slot/0", "LINE")]
    assert len(_moves(gp)) == 6

    # home == последняя точка маршрута 1 -> 0 (t1_over): не схлопывается.
    gp = toolchange(1, 0, LIB, home=LIB["t1_over"])
    assert [(m.point, m.kind) for m in _moves(gp)] == [
        ("t1_exit", "JOINT"),
        ("t1_pick", "LINE"),
        ("t1_over", "LINE"),
        ("t1_over", "JOINT"),
    ]


def test_li_sample_20_steps_14_records() -> None:
    """Образец DESIGN п.7: «Л+И» на листе — 20 шагов (14 ходов, 6 скоростей) и 14 записей."""
    gp = draw(LI, **PEN)
    assert len(gp.program.steps) == 20
    assert len(_moves(gp)) == 14
    assert len(_compile(gp).records) == 14
    assert all(p.frame == "sheet" and p.hand == 1 and p.rz == 0.0 for p in gp.points.values())


def test_draw_edge_strokes() -> None:
    """Штрих-«точка», повторы точек, штрих из конца предыдущего: ходов нулевой длины нет."""
    pd, pu, pl = -100.0, -95.0, -85.0  # Z пера в базе при PEN и lift 10
    point_rows = [
        (310.0, -90.0, pu, 0.0, "JOINT", "SPEED_PCT", 30),
        (310.0, -90.0, pd, 0.0, "LINE", "SPEED_PCT", 100),
        (310.0, -90.0, pl, 0.0, "LINE", "NONE", 0),
    ]
    assert _rows(draw((((10, 10),),), **PEN)) == point_rows  # СК листа — чистый сдвиг: числа точные
    assert _rows(draw((((10, 10),) * 3,), **PEN)) == point_rows  # СК листа — чистый сдвиг: числа точные

    rows = _rows(draw((((0, 0), (0, 0), (5, 5)),), **PEN))
    assert [(r[0], r[1], r[2], r[4]) for r in rows] == [
        (300.0, -100.0, pu, "JOINT"),
        (300.0, -100.0, pd, "LINE"),
        (305.0, -95.0, pd, "LINE"),
        (305.0, -95.0, pl, "LINE"),
    ]

    rows = _rows(draw((((0, 0), (10, 0)), ((10, 0), (10, 10))), **PEN))
    for a, b in zip(rows, rows[1:], strict=False):
        assert not (a[2] == pu and a[:3] == b[:3]), "два хода подряд в одну точку на высоте pen_up"
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (300.0, -100.0, pu),
        (300.0, -100.0, pd),
        (310.0, -100.0, pd),
        (310.0, -100.0, pu),  # подъём; переезд пропущен
        (310.0, -100.0, pd),
        (310.0, -90.0, pd),
        (310.0, -90.0, pl),
    ]


def test_draw_rejects_bad_arguments() -> None:
    """Плохие аргументы `draw` → `GeneratorError`; скорость вне диапазона → `ValueError` валидации `Action`."""
    for bad in (
        {"strokes": ()},
        {"strokes": (((0, 0),), ())},
        {"pen_up": 0.0},
        {"pen_up": -1.0},
        {"lift_mm": -0.5},
        {"max_pass_run": 0},
    ):
        kw = {"strokes": LI, **PEN, **bad}
        with pytest.raises(GeneratorError):
            draw(kw.pop("strokes"), **kw)
    draw(LI, **PEN, lift_mm=0.0, max_pass_run=1)  # границы допустимого собираются
    with pytest.raises(ValueError):
        draw(LI, **PEN, draw_speed_pct=0)
    with pytest.raises(GeneratorError):
        circle_stroke(0, 0, -1)
    with pytest.raises(GeneratorError):
        square_stroke(0, 0, 10, 0)


def test_return_slot_offsets_in_slot_frame() -> None:
    """Слот в СК с поворотом 30°: все точки в СК слота, сдвиг и подъём — по осям СК, а не базы."""
    rot = FrameDef(
        name="rot", origin=(300, 0, -100), on_x=(386.6025403784, 50, -100), in_plane=(250, 86.6025403784, -100)
    )
    slot = Point(name="slot", x=10, y=20, z=5, rz=0, hand=1, frame="rot")
    gp = return_slot(slot)
    assert {p.frame for p in gp.points.values()} == {"rot"}
    xyz = [(gp.points[m.point].x, gp.points[m.point].y, gp.points[m.point].z) for m in _moves(gp)]
    assert xyz == [(10, 20, 25), (10, 20, 5), (10, 20, 25), (110, 20, 25), (110, 20, 5)]
    rows = _rows(gp, {"rot": rot})
    # Сдвиг (110, 20) в СК: x = 300 + 110·cos30 − 20·sin30, y = 110·sin30 + 20·cos30.
    assert rows[4][:3] == pytest.approx((385.2627944163, 72.3205080757, -75.0), abs=1e-6)
    with pytest.raises(GeneratorError):
        return_slot(slot, lift_mm=0)


def test_toolchange_missing_points_named() -> None:
    """Одна ошибка со ВСЕМИ недостающими точками маршрута по алфавиту; чужие точки не требуются."""
    partial = {k: v for k, v in LIB.items() if k not in ("t2_pick", "t1_exit")}
    with pytest.raises(GeneratorError) as info:
        toolchange(1, 2, partial)
    assert str(info.value) == "обучите точки: t1_exit, t2_pick"
    only_1 = {k: v for k, v in LIB.items() if k.startswith("t1_")}
    assert [m.point for m in _moves(toolchange(0, 1, only_1))] == ["t1_over", "t1_pick", "t1_exit"]
    with pytest.raises(GeneratorError) as info:
        toolchange(0, 2, only_1)
    assert str(info.value) == "обучите точки: t2_exit, t2_over, t2_pick"


def test_toolchange_rejects_same_and_unknown_tool() -> None:
    """Совпадающий номер и неизвестный номер → `GeneratorError`; номер в тексте не называется."""
    for cur, tgt in ((1, 1), (0, 0)):
        with pytest.raises(GeneratorError):
            toolchange(cur, tgt, LIB)
    for cur, tgt in ((3, 1), (1, -1)):
        with pytest.raises(GeneratorError) as info:
            toolchange(cur, tgt, LIB)
        text = str(info.value)
        assert text == "неизвестный номер инструмента"
        assert "3" not in text and "-1" not in text


def test_home_conflict_and_points_closed() -> None:
    """Чужая точка с занятым именем → «конфликт имён точек»; `points` — ровно точки ходов программы."""
    fake = Point(name="t1_over", x=300, y=-210, z=-40, rz=-100, hand=1)
    with pytest.raises(GeneratorError) as info:
        toolchange(1, 0, LIB, home=fake)
    assert "конфликт имён точек" in str(info.value)
    with pytest.raises(GeneratorError):
        draw(LI, **PEN, home=Point(name="draw/0", x=300, y=-210, z=-40, rz=-100, hand=1))
    for label, gp in _all_generated().items():
        assert set(gp.points) == {m.point for m in _moves(gp)}, label
        assert all(name == p.name for name, p in gp.points.items()), label
