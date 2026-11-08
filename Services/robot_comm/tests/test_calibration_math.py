"""Тесты автора T5.4m: математика калибровок ``Services.robot_comm.calibration`` (R1-R10 и пограничные случаи).

Purpose:
    Закрепить поведение ``belt_from_marks``, ``fit_frame``, ``check_tool_points``: числа результата, порядок
    проверок, тексты отказов, чистые типы Python и отсутствие ``numpy`` в импорте ``Services.robot_comm``.
    Слепая приёмка лежит рядом (``test_t54_calibration_acceptance.py``) и не дублируется.

Как устроено:
    Ожидаемые числа и тексты - литералы (не импорт констант кода). Случайный шум - ``random.Random(seed)``.
    Чистая математика: потоков и ввода-вывода нет, ``bounded`` не нужен.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import math
import random
import subprocess
import sys

import pytest

from Services.robot_comm.calibration import (
    CalibrationError,
    ToolCheck,
    belt_from_marks,
    check_tool_points,
    fit_frame,
)
from Services.robot_comm.programs import FrameDef, Point

_SHEET = ((0.0, 0.0, 0.0), (297.0, 0.0, 0.0), (0.0, 210.0, 0.0))
_SHIFT = (100.0, 50.0, -20.0)


def _to_base(yaw_deg: float, shift: tuple[float, float, float], p: tuple[float, float, float]):
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    return (c * p[0] - s * p[1] + shift[0], s * p[0] + c * p[1] + shift[1], p[2] + shift[2])


def _belt_refusal(text: str, *args) -> None:
    with pytest.raises(CalibrationError) as excinfo:
        belt_from_marks(*args)
    assert str(excinfo.value) == text


def _frame_refusal(text: str, base, local) -> None:
    with pytest.raises(CalibrationError) as excinfo:
        fit_frame(base, local)
    assert str(excinfo.value) == text


# --- R1-R5: лента ----------------------------------------------------------------------------------


def test_belt_known_travel() -> None:
    """R1: (250,-100)->(250,100), энкодер 1000->2384 -> ось +Y, сырое 14451, коэффициент 200/1384, отклонение 0."""
    res = belt_from_marks((250.0, -100.0), 1000, (250.0, 100.0), 2384)
    assert res.direction == 1
    assert res.raw_factor == 14451
    assert abs(res.factor_mm_per_imp - 200.0 / 1384.0) < 1e-12
    assert res.axis_dev_deg == 0
    assert res.delta_enc == 1384
    assert res.travel_mm == 200.0


def test_belt_negative_delta_flips_axis() -> None:
    """R2: те же точки, enc2 = -384 (энкодер убывает на 1384) -> ось 3 (-Y), delta_enc -1384."""
    res = belt_from_marks((250.0, -100.0), 1000, (250.0, 100.0), -384)
    assert res.direction == 3
    assert res.delta_enc == -1384
    assert res.raw_factor == 14451


def test_belt_encoder_wrap() -> None:
    """R3: переход 32-битного энкодера через границу вперёд -> delta_enc 1384, коэффициент прежний."""
    res = belt_from_marks((250.0, -100.0), 2**31 - 100, (250.0, 100.0), -(2**31) + 1284)
    assert res.delta_enc == 1384
    assert res.raw_factor == 14451


def test_belt_projection_on_axis() -> None:
    """R4: ход 200 мм под 0.5 градуса к +X, delta 1384 -> коэффициент берётся по проекции на ось (1e-9)."""
    tilt = math.radians(0.5)
    p2 = (200.0 * math.cos(tilt), 200.0 * math.sin(tilt))
    res = belt_from_marks((0.0, 0.0), 0, p2, 1384)
    assert res.direction == 0
    assert abs(res.factor_mm_per_imp - 200.0 * math.cos(tilt) / 1384.0) < 1e-9
    assert abs(res.axis_dev_deg - 0.5) < 1e-6
    assert abs(res.travel_mm - 200.0) < 1e-9


def test_belt_refusals() -> None:
    """R5: энкодер без изменения; ход 99.9 мм; угол 1.2 градуса; nan -> четыре разных текста (литералы)."""
    _belt_refusal("энкодер не изменился между отметками", (250.0, -100.0), 1000, (250.0, 100.0), 1000)
    _belt_refusal("мало хода ленты между отметками", (0.0, 0.0), 0, (99.9, 0.0), 692)
    tilt = math.radians(1.2)
    _belt_refusal("лента не вдоль оси робота", (0.0, 0.0), 0, (200.0 * math.cos(tilt), 200.0 * math.sin(tilt)), 1384)
    _belt_refusal("неверные отметки ленты", (math.nan, 0.0), 0, (200.0, 0.0), 1384)


def test_belt_travel_exactly_hundred_passes() -> None:
    """Граница: ход ровно 100.0 мм проходит, 99.9 мм - отказ."""
    assert belt_from_marks((0.0, 0.0), 0, (100.0, 0.0), 692).travel_mm == 100.0
    _belt_refusal("мало хода ленты между отметками", (0.0, 0.0), 0, (99.9, 0.0), 692)


def test_belt_factor_below_one_raw_unit_refused() -> None:
    """Сырое значение < 1 (коэффициент меньше 1e-5 мм/имп) -> отказ о диапазоне параметра."""
    _belt_refusal("коэффициент ленты вне диапазона параметра", (0.0, 0.0), 0, (100.0, 0.0), 2**30)


def test_belt_non_finite_precedes_encoder_check() -> None:
    """Порядок: бесконечная координата при равном энкодере - «неверные отметки», не «энкодер не изменился»."""
    _belt_refusal("неверные отметки ленты", (math.inf, 0.0), 5, (0.0, 0.0), 5)


def test_belt_numbers_are_plain_python() -> None:
    """Числа результата - float/int Python, не numpy."""
    res = belt_from_marks((250.0, -100.0), 1000, (250.0, 100.0), 2384)
    assert [type(v) for v in (res.factor_mm_per_imp, res.axis_dev_deg, res.travel_mm)] == [float] * 3
    assert [type(v) for v in (res.raw_factor, res.direction, res.delta_enc)] == [int] * 3


# --- R6-R8, R10: СК --------------------------------------------------------------------------------


def test_fit_frame_exact() -> None:
    """R6: yaw 30, сдвиг (100,50,-20) -> yaw 30, невязка ~0, FrameDef переводит номиналы обратно в базу."""
    base = [_to_base(30.0, _SHIFT, p) for p in _SHEET]
    fit = fit_frame(base, list(_SHEET))
    assert abs(fit.yaw_deg - 30.0) < 1e-9
    assert fit.max_residual_mm < 1e-9
    frame = FrameDef(name="t", origin=fit.origin, on_x=fit.on_x, in_plane=fit.in_plane)
    for loc, want in zip(_SHEET, base, strict=True):
        got = frame.to_base(loc[0], loc[1], loc[2], 0)[:3]
        assert math.dist(got, want) < 1e-9


def test_fit_frame_residual_refusal() -> None:
    """R7: база второй точки сдвинута на +2.0 мм вдоль локальной Y (в листе) -> невязка; номинал в см -> то же."""
    base = [_to_base(30.0, _SHIFT, p) for p in _SHEET]
    base[1] = _to_base(30.0, _SHIFT, (297.0, 2.0, 0.0))
    _frame_refusal("точки не совпадают с размерами СК", base, list(_SHEET))
    base_ok = [_to_base(30.0, _SHIFT, p) for p in _SHEET]
    local_cm = [(x * 0.1, y * 0.1, z * 0.1) for x, y, z in _SHEET]
    _frame_refusal("точки не совпадают с размерами СК", base_ok, local_cm)


def test_fit_frame_mirror_degenerate_upside_down() -> None:
    """R8: зеркало (y x -1) -> «Z вниз» (не невязка); коллинеарные -> вырождение; поворот 180 вокруг X -> «Z вниз»."""
    base = [_to_base(30.0, _SHIFT, p) for p in _SHEET]
    mirrored = [(x, -y, z) for x, y, z in _SHEET]
    _frame_refusal("СК перевёрнута: ось Z вниз", base, mirrored)
    line = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (200.0, 0.0, 0.0)]
    _frame_refusal("точки СК вырождены", [_to_base(30.0, _SHIFT, p) for p in line], line)
    flipped = [(x + 300.0, -y - 100.0, -z - 40.0) for x, y, z in _SHEET]
    _frame_refusal("СК перевёрнута: ось Z вниз", flipped, list(_SHEET))


def test_fit_frame_residual_checked_before_upside_down() -> None:
    """Порядок (г) -> (д): грубая ошибка в перевёрнутом наборе даёт невязку, не «Z вниз»."""
    flipped = [(x + 300.0, -y - 100.0, -z - 40.0) for x, y, z in _SHEET]
    flipped[1] = (flipped[1][0], flipped[1][1] + 30.0, flipped[1][2])
    _frame_refusal("точки не совпадают с размерами СК", flipped, list(_SHEET))


def test_fit_frame_bad_points() -> None:
    """Две точки; разные длины; нечисловая координата в базе - «неверные точки», до проверки вырождения."""
    base = [_to_base(30.0, _SHIFT, p) for p in _SHEET]
    _frame_refusal("неверные точки подгонки СК", base[:2], list(_SHEET[:2]))
    _frame_refusal("неверные точки подгонки СК", base, list(_SHEET[:2]))
    base[2] = (base[2][0], math.nan, base[2][2])
    _frame_refusal("неверные точки подгонки СК", base, list(_SHEET))
    line = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (200.0, 0.0, 0.0)]
    _frame_refusal("неверные точки подгонки СК", [(0.0, math.inf, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)], line)


def test_fit_frame_custom_residual_limit() -> None:
    """Параметр ``max_residual_mm``: сдвиг 2.0 мм в листе проходит при пороге 5.0 и отказывает при умолчании."""
    base = [_to_base(30.0, _SHIFT, p) for p in _SHEET]
    base[1] = _to_base(30.0, _SHIFT, (297.0, 2.0, 0.0))
    assert fit_frame(base, list(_SHEET), max_residual_mm=5.0).max_residual_mm > 0.3
    _frame_refusal("точки не совпадают с размерами СК", base, list(_SHEET))


def test_fit_frame_numbers_are_plain_python() -> None:
    """Поля результата - float Python (годятся для YAML и IPC)."""
    base = [_to_base(30.0, _SHIFT, p) for p in _SHEET]
    fit = fit_frame(base, list(_SHEET))
    assert type(fit.yaw_deg) is float
    assert type(fit.max_residual_mm) is float
    assert all(type(v) is float for v in (*fit.origin, *fit.on_x, *fit.in_plane, *fit.residuals_mm))
    assert len(fit.residuals_mm) == 3


def test_fit_frame_four_points_noise() -> None:
    """R10: 4 точки, шум +-0.1 мм, 200 случайных поз (seed) -> ошибка yaw <= 0.1 градуса."""
    rng = random.Random(540)
    local = [*_SHEET, (297.0, 210.0, 0.0)]
    for pose in range(200):
        yaw = rng.uniform(-180.0, 180.0)
        shift = (rng.uniform(-300.0, 300.0), rng.uniform(-300.0, 300.0), rng.uniform(-50.0, 50.0))
        base = []
        for p in local:
            b = _to_base(yaw, shift, p)
            base.append(tuple(v + rng.uniform(-0.1, 0.1) for v in b))
        fit = fit_frame(base, local)
        err = abs((fit.yaw_deg - yaw + 180.0) % 360.0 - 180.0)
        assert err <= 0.1, f"поза {pose}: ошибка {err:.4f}"


# --- R9: инструменты -------------------------------------------------------------------------------


def _pt(name: str, z: float, frame: str | None = None) -> Point:
    return Point(name=name, x=1.0, y=2.0, z=z, rz=0.0, hand=0, frame=frame)


def _full() -> dict[str, Point]:
    return {
        "t1_over": _pt("t1_over", -30.0),
        "t1_pick": _pt("t1_pick", -60.0),
        "t1_exit": _pt("t1_exit", -30.0),
        "t2_over": _pt("t2_over", -30.0),
        "t2_pick": _pt("t2_pick", -60.0),
        "t2_exit": _pt("t2_exit", -30.0),
    }


def test_check_tool_points() -> None:
    """R9: t1 с over.z == pick.z и точкой в листе, у t2 нет t2_exit -> результат по коду."""
    pts = _full()
    pts["t1_over"] = _pt("t1_over", -60.0)
    pts["t1_exit"] = _pt("t1_exit", -30.0, frame="sheet")
    del pts["t2_exit"]
    assert check_tool_points(pts) == [
        ToolCheck(1, False, (), ("not_in_base", "over_not_above_pick")),
        ToolCheck(2, False, ("t2_exit",), ()),
    ]
    assert check_tool_points(_full()) == [ToolCheck(1, True, (), ()), ToolCheck(2, True, (), ())]


def test_check_tool_points_empty_map_and_tools_order() -> None:
    """Пустая карта: пропуски по алфавиту, у инструмента 2 и транзитная точка; свои таблицы - по возрастанию номера."""
    checks = check_tool_points({})
    assert checks[0].missing == ("t1_exit", "t1_over", "t1_pick")
    assert checks[1].missing == ("t1_over", "t2_exit", "t2_over", "t2_pick")
    custom = check_tool_points({}, tools={3: ("c", "a", "b"), 1: ("z", "y", "x")}, transit={})
    assert [(c.tool, c.missing) for c in custom] == [(1, ("x", "y", "z")), (3, ("a", "b", "c"))]


def test_check_tool_points_clearance_boundary() -> None:
    """Зазор ровно 1.0 мм допустим, 0.5 мм - нет; свой порог ``min_clear_mm`` действует."""
    pts = _full()
    pts["t1_over"] = _pt("t1_over", -59.0)
    assert check_tool_points(pts)[0].problems == ()
    pts["t1_over"] = _pt("t1_over", -59.5)
    assert check_tool_points(pts)[0].problems == ("over_not_above_pick",)
    assert check_tool_points(pts, min_clear_mm=0.2)[0].problems == ()


# --- импорт ------------------------------------------------------------------------------------------


def test_import_robot_comm_does_not_load_numpy() -> None:
    """Импорт ``Services.robot_comm`` не тянет ``numpy``; импорт ``calibration`` тянет (после подгонки СК)."""
    code = (
        "import sys; import Services.robot_comm; print('numpy' in sys.modules); "
        "import Services.robot_comm.calibration; print('numpy' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL, check=True
    )
    assert out.stdout.split() == ["False", "True"]
