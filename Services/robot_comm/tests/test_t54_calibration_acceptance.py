"""Слепые приёмочные тесты T5.4, часть 1: математика калибровки робота v2 (A1-A9).

Purpose:
    Закрепить контракт пакета ``Services.robot_comm.calibration`` по файлу приёмки (критерии A1-A9) и докстрокам
    публичных заглушек: ``belt_from_marks``, ``fit_frame``, ``check_tool_points``, ``CalibrationError``.
    Вход тестера - только файл приёмки и публичные заглушки; тела функций не читались.

Как устроено:
    * Ожидаемые значения - литералы приёмки (0.14447 мм/имп, 1384 импульса, 14451, пороги 1.0 / 100 мм / 0.5 мм);
      ничего не пересчитывается кодом под тестом. Входные данные шумных прогонов строит ``random.Random`` с
      фиксированным seed (чтобы красное/зелёное воспроизводилось).
    * Чистая математика: потоков и ввода-вывода нет, поэтому ``bounded`` не нужен.
    * Имена пакета импортируются на уровне модуля: заглушки существуют, красное даёт ``NotImplementedError``.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

import math
import random

import pytest

from Services.robot_comm.calibration import (
    CalibrationError,
    belt_from_marks,
    check_tool_points,
    fit_frame,
)
from Services.robot_comm.programs import FrameDef, Point

# --------------------------------------------------------------------------------------------------
# Литералы приёмки
# --------------------------------------------------------------------------------------------------

TEXT_BAD_MARKS = "неверные отметки ленты"
TEXT_NO_ENCODER = "энкодер не изменился между отметками"
TEXT_SHORT = "мало хода ленты между отметками"
TEXT_OFF_AXIS = "лента не вдоль оси робота"
TEXT_BAD_POINTS = "неверные точки подгонки СК"
TEXT_DEGENERATE = "точки СК вырождены"
TEXT_RESIDUAL = "точки не совпадают с размерами СК"
TEXT_UPSIDE_DOWN = "СК перевёрнута: ось Z вниз"

# Направление хода детали при РОСТЕ энкодера: индекс = P_BELT_DIR (0 +X, 1 +Y, 2 -X, 3 -Y)
_AXES = ((1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0))

_TRUE_FACTOR = 0.14447  # мм/имп, приёмка A1
_TRAVEL_IMP = 1384  # 200 мм / 0.14447 = 1384.4 имп (округление до целого импульса)

# Углы листа A4 (номинал СК), мм
_SHEET = ((0.0, 0.0, 0.0), (297.0, 0.0, 0.0), (0.0, 210.0, 0.0))


def _marks_along(axis: int, start: tuple[float, float], enc1: int, delta: int, factor: float):
    """Две отметки: деталь шла вдоль оси ``axis`` при росте энкодера на ``delta`` имп (``delta`` > 0)."""
    ax, ay = _AXES[axis]
    travel = delta * factor
    return start, enc1, (start[0] + ax * travel, start[1] + ay * travel), enc1 + delta


def _expect_refusal(text: str, *args, **kwargs) -> None:
    with pytest.raises(CalibrationError) as excinfo:
        belt_from_marks(*args, **kwargs)
    assert str(excinfo.value) == text


def _rot_z(yaw_deg: float, v: tuple[float, float, float]) -> tuple[float, float, float]:
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    return (c * v[0] - s * v[1], s * v[0] + c * v[1], v[2])


def _to_base(yaw_deg: float, shift: tuple[float, float, float], local: tuple[float, float, float]):
    r = _rot_z(yaw_deg, local)
    return (r[0] + shift[0], r[1] + shift[1], r[2] + shift[2])


def _wrap_deg(diff: float) -> float:
    """Разность углов, приведённая в [-180, 180) (по модулю 360)."""
    return (diff + 180.0) % 360.0 - 180.0


def _expect_frame_refusal(text: str, base, local) -> None:
    with pytest.raises(CalibrationError) as excinfo:
        fit_frame(base, local)
    assert str(excinfo.value) == text


# --------------------------------------------------------------------------------------------------
# A1-A5 - лента
# --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("axis", [0, 1, 2, 3])
def test_a1_belt_factor_error_under_half_percent_and_direction_per_axis(axis: int) -> None:
    """A1: ход ~200 мм вдоль оси, шум +-0.1 мм по X и Y, 100 прогонов seed -> ошибка коэффициента < 0.5 %, ось верна."""
    rng = random.Random(54000 + axis)
    for run in range(100):
        start = (rng.uniform(-300.0, 300.0), rng.uniform(-300.0, 300.0))
        enc1 = rng.randint(-1_000_000, 1_000_000)
        p1, e1, p2, e2 = _marks_along(axis, start, enc1, _TRAVEL_IMP, _TRUE_FACTOR)
        n1 = (p1[0] + rng.uniform(-0.1, 0.1), p1[1] + rng.uniform(-0.1, 0.1))
        n2 = (p2[0] + rng.uniform(-0.1, 0.1), p2[1] + rng.uniform(-0.1, 0.1))
        res = belt_from_marks(n1, e1, n2, e2)
        rel = abs(res.factor_mm_per_imp - _TRUE_FACTOR) / _TRUE_FACTOR
        assert rel < 0.005, f"ось {axis}, прогон {run}: ошибка {rel:.5f}"
        assert res.direction == axis, f"ось {axis}, прогон {run}: direction={res.direction}"


def test_a1_noise_free_belt_literals() -> None:
    """A1 (без шума): (250,-100,enc 1000) -> (250,100,enc 2384): 200/1384 мм/имп, сырое 14451, ось +Y, ход 200 мм."""
    res = belt_from_marks((250.0, -100.0), 1000, (250.0, 100.0), 2384)
    assert res.raw_factor == 14451
    assert res.factor_mm_per_imp == pytest.approx(0.1445087, abs=1e-6)
    assert res.direction == 1
    assert res.delta_enc == 1384
    assert res.travel_mm == pytest.approx(200.0, abs=1e-9)
    assert res.axis_dev_deg == pytest.approx(0.0, abs=1e-9)


def test_belt_result_numbers_are_plain_python() -> None:
    """Post докстроки: все числа результата ленты - ``float`` / ``int`` Python (уходят в YAML и JSON ответа команды)."""
    res = belt_from_marks((250.0, -100.0), 1000, (250.0, 100.0), 2384)
    assert type(res.factor_mm_per_imp) is float
    assert type(res.raw_factor) is int
    assert type(res.direction) is int
    assert type(res.axis_dev_deg) is float
    assert type(res.travel_mm) is float
    assert type(res.delta_enc) is int


def test_a2_decreasing_encoder_along_plus_y_gives_direction_3() -> None:
    """A2: ход 200 мм по +Y, энкодер убывает -> часть идёт по -Y при РОСТЕ энкодера: direction 3, delta_enc < 0."""
    res = belt_from_marks((250.0, -100.0), 2384, (250.0, 100.0), 1000)
    assert res.direction == 3
    assert res.delta_enc == -1384
    assert res.raw_factor == 14451  # коэффициент положителен и не зависит от знака хода


def test_a3_encoder_wrap_across_32_bit_boundary_forward() -> None:
    """A3: 2**31-100 -> -2**31+1284 (переход через границу вперёд): delta_enc == 1384, коэффициент прежний."""
    res = belt_from_marks((250.0, -100.0), 2**31 - 100, (250.0, 100.0), -(2**31) + 1284)
    assert res.delta_enc == 1384
    assert res.raw_factor == 14451
    assert res.direction == 1


def test_a3_encoder_wrap_across_32_bit_boundary_backward() -> None:
    """A3 (обратно): -2**31+1284 -> 2**31-100 при ходе по +Y: энкодер убывает на 1384 -> delta_enc == -1384, ось -Y."""
    res = belt_from_marks((250.0, -100.0), -(2**31) + 1284, (250.0, 100.0), 2**31 - 100)
    assert res.delta_enc == -1384
    assert res.direction == 3


def test_a4_belt_tilted_half_degree_succeeds_with_axis_deviation() -> None:
    """A4: ход 200 мм под 0.5 градуса к +X -> успех, axis_dev_deg ~ 0.5, ось +X."""
    tilt = math.radians(0.5)
    p2 = (200.0 * math.cos(tilt), 200.0 * math.sin(tilt))
    res = belt_from_marks((0.0, 0.0), 1000, p2, 1000 + _TRAVEL_IMP)
    assert res.direction == 0
    assert res.axis_dev_deg == pytest.approx(0.5, abs=0.01)


def test_a4_belt_tilted_minus_half_degree_deviation_is_unsigned() -> None:
    """A4: наклон в другую сторону (-0.5 градуса): отклонение неотрицательно и ~ 0.5."""
    tilt = math.radians(-0.5)
    p2 = (200.0 * math.cos(tilt), 200.0 * math.sin(tilt))
    res = belt_from_marks((0.0, 0.0), 1000, p2, 1000 + _TRAVEL_IMP)
    assert res.direction == 0
    assert res.axis_dev_deg == pytest.approx(0.5, abs=0.01)


def test_a4_belt_tilted_one_and_half_degrees_refused() -> None:
    """A4: под 1.5 градуса к оси - отказ «лента не вдоль оси робота»."""
    tilt = math.radians(1.5)
    p2 = (200.0 * math.cos(tilt), 200.0 * math.sin(tilt))
    _expect_refusal(TEXT_OFF_AXIS, (0.0, 0.0), 1000, p2, 1000 + _TRAVEL_IMP)


def test_a4_axis_deviation_threshold_default_is_one_degree_just_inside() -> None:
    """Порог по умолчанию <= 1.0 градуса: 0.95 градуса проходит (граница изнутри)."""
    tilt = math.radians(0.95)
    p2 = (200.0 * math.cos(tilt), 200.0 * math.sin(tilt))
    res = belt_from_marks((0.0, 0.0), 1000, p2, 1000 + _TRAVEL_IMP)
    assert res.axis_dev_deg == pytest.approx(0.95, abs=0.01)


def test_a4_axis_deviation_threshold_default_is_one_degree_just_outside() -> None:
    """Порог по умолчанию <= 1.0 градуса: 1.05 градуса - отказ (граница снаружи)."""
    tilt = math.radians(1.05)
    p2 = (200.0 * math.cos(tilt), 200.0 * math.sin(tilt))
    _expect_refusal(TEXT_OFF_AXIS, (0.0, 0.0), 1000, p2, 1000 + _TRAVEL_IMP)


def test_a4_tilt_near_minus_y_axis_picks_nearest_axis() -> None:
    """Наклон 0.5 градуса от оси -Y (энкодер растёт): ближайшая ось 3, отклонение ~ 0.5 (а не ~ 89.5 от +X)."""
    tilt = math.radians(0.5)
    p2 = (200.0 * math.sin(tilt), -200.0 * math.cos(tilt))
    res = belt_from_marks((0.0, 0.0), 1000, p2, 1000 + _TRAVEL_IMP)
    assert res.direction == 3
    assert res.axis_dev_deg == pytest.approx(0.5, abs=0.01)


def test_a5_equal_encoder_refused() -> None:
    """A5: энкодер равен при ходе 200 мм -> «энкодер не изменился между отметками»."""
    _expect_refusal(TEXT_NO_ENCODER, (250.0, -100.0), 1000, (250.0, 100.0), 1000)


def test_a5_short_travel_sixty_mm_refused() -> None:
    """A5: ход 60 мм (порог 100 мм) -> «мало хода ленты между отметками»."""
    _expect_refusal(TEXT_SHORT, (250.0, -30.0), 1000, (250.0, 30.0), 1415)


def test_a5_travel_threshold_hundred_mm_inclusive() -> None:
    """Порог хода >= 100 мм: ровно 100.0 мм проходит (граница изнутри)."""
    res = belt_from_marks((0.0, 0.0), 1000, (100.0, 0.0), 1692)
    assert res.travel_mm == pytest.approx(100.0, abs=1e-9)
    assert res.direction == 0


def test_a5_travel_just_below_threshold_refused() -> None:
    """Порог хода >= 100 мм: 99.9 мм - отказ (граница снаружи)."""
    _expect_refusal(TEXT_SHORT, (0.0, 0.0), 1000, (99.9, 0.0), 1692)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize("slot", ["x1", "y1", "x2", "y2"])
def test_a5_non_finite_coordinate_refused(slot: str, bad: float) -> None:
    """A5: нечисловая координата (nan; по докстроке и inf) в любой из четырёх позиций -> «неверные отметки ленты»."""
    coords = {"x1": 250.0, "y1": -100.0, "x2": 250.0, "y2": 100.0}
    coords[slot] = bad
    _expect_refusal(TEXT_BAD_MARKS, (coords["x1"], coords["y1"]), 1000, (coords["x2"], coords["y2"]), 2384)


# --------------------------------------------------------------------------------------------------
# A6-A8 - СК
# --------------------------------------------------------------------------------------------------


def test_a6_three_point_frame_with_noise_recovers_yaw_within_tenth_degree() -> None:
    """A6: углы листа A4, шум +-0.1 мм по каждой оси, 200 поз seed -> yaw до 0.1 градуса, начало до 0.5 мм."""
    rng = random.Random(54006)
    for pose in range(200):
        yaw = rng.uniform(-180.0, 180.0)
        shift = (rng.uniform(-300.0, 300.0), rng.uniform(-300.0, 300.0), rng.uniform(-50.0, 50.0))
        base = []
        for local in _SHEET:
            b = _to_base(yaw, shift, local)
            base.append((b[0] + rng.uniform(-0.1, 0.1), b[1] + rng.uniform(-0.1, 0.1), b[2] + rng.uniform(-0.1, 0.1)))
        fit = fit_frame(base, list(_SHEET))
        err = abs(_wrap_deg(fit.yaw_deg - yaw))
        assert err <= 0.1, f"поза {pose}: yaw={yaw:.3f}, ошибка {err:.4f} градуса"
        d_origin = math.dist(fit.origin, shift)
        assert d_origin <= 0.5, f"поза {pose}: начало отстоит на {d_origin:.3f} мм"


def test_a6_yaw_wrap_near_180_degrees() -> None:
    """A6 (граница): истинный поворот около +-180 градусов - оценка совпадает по модулю 360, а не расходится на 360."""
    for yaw in (-180.0, 179.95, -179.95):
        base = [_to_base(yaw, (100.0, 50.0, -20.0), p) for p in _SHEET]
        fit = fit_frame(base, list(_SHEET))
        assert abs(_wrap_deg(fit.yaw_deg - yaw)) <= 1e-6, f"yaw={yaw}: получили {fit.yaw_deg}"


def test_a7_four_points_exact_fit_has_zero_residuals() -> None:
    """A7: четыре угла листа без шума, поворот 30 градусов -> невязки < 1e-6 мм по каждой из четырёх точек."""
    local = [*_SHEET, (297.0, 210.0, 0.0)]
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in local]
    fit = fit_frame(base, local)
    assert len(fit.residuals_mm) == 4
    assert all(r < 1e-6 for r in fit.residuals_mm), fit.residuals_mm
    assert fit.max_residual_mm < 1e-6
    assert fit.yaw_deg == pytest.approx(30.0, abs=1e-6)


def test_a7_framedef_from_fit_maps_each_nominal_back_to_base() -> None:
    """A7: ``FrameDef`` из полей результата (origin, on_x, in_plane) переводит каждый номинал в базу до 1e-6 мм."""
    local = [*_SHEET, (297.0, 210.0, 0.0)]
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in local]
    fit = fit_frame(base, local)
    frame = FrameDef(name="sheet", origin=fit.origin, on_x=fit.on_x, in_plane=fit.in_plane)
    for loc, want in zip(local, base, strict=True):
        got = frame.to_base(loc[0], loc[1], loc[2], 0.0)[:3]
        assert math.dist(got, want) < 1e-6, f"номинал {loc}: получили {got}, ожидали {want}"


def test_frame_fit_numbers_are_plain_python() -> None:
    """Post докстроки: поля ``FrameFit`` - ``float`` Python / кортежи ``float`` (годятся для YAML и JSON команды)."""
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in _SHEET]
    fit = fit_frame(base, list(_SHEET))
    assert type(fit.yaw_deg) is float
    assert type(fit.max_residual_mm) is float
    for triple in (fit.origin, fit.on_x, fit.in_plane):
        assert len(triple) == 3
        assert all(type(v) is float for v in triple)
    assert all(type(v) is float for v in fit.residuals_mm)


def test_frame_fit_on_x_and_in_plane_are_offset_points_of_local_axes() -> None:
    """Контракт ``FrameFit``: ``on_x`` - база-образ локальной (100, 0, 0), ``in_plane`` - локальной (0, 100, 0)."""
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in _SHEET]
    fit = fit_frame(base, list(_SHEET))
    want_on_x = _to_base(30.0, (300.0, -100.0, -40.0), (100.0, 0.0, 0.0))
    want_in_plane = _to_base(30.0, (300.0, -100.0, -40.0), (0.0, 100.0, 0.0))
    assert math.dist(fit.on_x, want_on_x) < 1e-6
    assert math.dist(fit.in_plane, want_in_plane) < 1e-6


def test_a8_in_plane_shift_of_two_mm_refused_as_size_mismatch() -> None:
    """A8: база (297,0,0) сдвинута на +2.0 мм вдоль локальной Y (в листе), yaw 30 -> «не совпадают с размерами»."""
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in _SHEET]
    shifted = _to_base(30.0, (300.0, -100.0, -40.0), (297.0, 2.0, 0.0))
    base[1] = shifted
    _expect_frame_refusal(TEXT_RESIDUAL, base, list(_SHEET))


def test_a8_nominal_in_centimetres_refused_as_size_mismatch() -> None:
    """A8: номинал в сантиметрах (масштаб в 10 раз меньше) -> «точки не совпадают с размерами СК»."""
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in _SHEET]
    local_cm = [(0.0, 0.0, 0.0), (29.7, 0.0, 0.0), (0.0, 21.0, 0.0)]
    _expect_frame_refusal(TEXT_RESIDUAL, base, local_cm)


def test_a8_three_collinear_nominals_refused_as_degenerate() -> None:
    """A8: три коллинеарных номинала -> «точки СК вырождены»."""
    local = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (200.0, 0.0, 0.0)]
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in local]
    _expect_frame_refusal(TEXT_DEGENERATE, base, local)


def test_a8_mirrored_nominal_is_not_a_success() -> None:
    """A8: зеркальный номинал (y x -1) - не успех: отказ (перевёрнутая Z либо невязка), но не результат."""
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in _SHEET]
    mirrored = [(x, -y, z) for x, y, z in _SHEET]
    with pytest.raises(CalibrationError) as excinfo:
        fit_frame(base, mirrored)
    assert str(excinfo.value) in (TEXT_UPSIDE_DOWN, TEXT_RESIDUAL)


def test_a8_rotated_180_about_x_refused_as_upside_down() -> None:
    """A8: СК повёрнута на 180 градусов вокруг X (ось Z вниз): база = (x, -y, -z) от номинала -> «ось Z вниз»."""
    base = [(x + 300.0, -y - 100.0, -z - 40.0) for x, y, z in _SHEET]
    _expect_frame_refusal(TEXT_UPSIDE_DOWN, base, list(_SHEET))


def test_a8_two_points_refused_as_bad_points() -> None:
    """A8: две точки -> «неверные точки подгонки СК»."""
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in _SHEET[:2]]
    _expect_frame_refusal(TEXT_BAD_POINTS, base, list(_SHEET[:2]))


def test_frame_unequal_lengths_refused_as_bad_points() -> None:
    """Докстрока ``fit_frame``: длины ``base`` и ``local`` не равны -> «неверные точки подгонки СК»."""
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in _SHEET]
    _expect_frame_refusal(TEXT_BAD_POINTS, base, list(_SHEET[:2]))


def test_frame_non_finite_base_coordinate_refused_as_bad_points() -> None:
    """Докстрока ``fit_frame``: координата не конечна -> «неверные точки подгонки СК» (до проверки вырожденности)."""
    base = [_to_base(30.0, (300.0, -100.0, -40.0), p) for p in _SHEET]
    base[2] = (base[2][0], math.nan, base[2][2])
    _expect_frame_refusal(TEXT_BAD_POINTS, base, list(_SHEET))


# --------------------------------------------------------------------------------------------------
# A9 - инструменты
# --------------------------------------------------------------------------------------------------


def _pt(name: str, z: float, *, frame: str | None = None) -> Point:
    return Point(name=name, x=300.0, y=-100.0, z=z, rz=0.0, hand=1, frame=frame)


def _full_set(**overrides: Point | None) -> dict[str, Point]:
    """Полный набор t1/t2: «над» на -30, гнездо на -60, выход на -30; ``overrides[имя] = None`` убирает точку."""
    pts = {
        "t1_over": _pt("t1_over", -30.0),
        "t1_pick": _pt("t1_pick", -60.0),
        "t1_exit": _pt("t1_exit", -30.0),
        "t2_over": _pt("t2_over", -30.0),
        "t2_pick": _pt("t2_pick", -60.0),
        "t2_exit": _pt("t2_exit", -30.0),
    }
    for name, value in overrides.items():
        if value is None:
            del pts[name]
        else:
            pts[name] = value
    return pts


def test_a9_full_set_both_tools_ok() -> None:
    """A9: полный набор t1/t2, «над» выше гнезда -> два результата (1 и 2), оба ok, без пропусков и проблем."""
    checks = check_tool_points(_full_set())
    assert [c.tool for c in checks] == [1, 2]
    assert [c.ok for c in checks] == [True, True]
    assert [tuple(c.missing) for c in checks] == [(), ()]
    assert [tuple(c.problems) for c in checks] == [(), ()]


def test_a9_missing_t2_exit_reported_for_tool_2_only() -> None:
    """A9: нет ``t2_exit`` -> у инструмента 2 ``missing == ("t2_exit",)`` и не ok."""
    checks = check_tool_points(_full_set(t2_exit=None))
    tool2 = checks[1]
    assert tool2.tool == 2
    assert tool2.missing == ("t2_exit",)
    assert tool2.ok is False


def test_a9_missing_t2_exit_does_not_spoil_tool_1() -> None:
    """A9: пропажа ``t2_exit`` не затрагивает инструмент 1 (он по-прежнему ok)."""
    tool1 = check_tool_points(_full_set(t2_exit=None))[0]
    assert tool1.tool == 1
    assert tool1.ok is True
    assert tool1.missing == ()


def test_a9_over_at_pick_height_is_over_not_above_pick() -> None:
    """A9: ``t1_over`` на высоте ``t1_pick`` -> у инструмента 1 проблема ``over_not_above_pick`` и не ok."""
    checks = check_tool_points(_full_set(t1_over=_pt("t1_over", -60.0)))
    assert checks[0].problems == ("over_not_above_pick",)
    assert checks[0].ok is False
    assert checks[0].missing == ()


def test_a9_over_below_pick_is_over_not_above_pick() -> None:
    """«Над» ниже гнезда (разность отрицательна) - та же проблема."""
    checks = check_tool_points(_full_set(t1_over=_pt("t1_over", -80.0)))
    assert checks[0].problems == ("over_not_above_pick",)


def test_a9_clearance_one_mm_is_enough_and_half_mm_is_not() -> None:
    """Порог ``min_clear_mm`` = 1.0: зазор 1.0 мм - без проблем; 0.5 мм - ``over_not_above_pick`` (оба берега)."""
    at_threshold = check_tool_points(_full_set(t1_over=_pt("t1_over", -59.0)))
    below = check_tool_points(_full_set(t1_over=_pt("t1_over", -59.5)))
    assert at_threshold[0].problems == ()
    assert below[0].problems == ("over_not_above_pick",)


def test_a9_over_problem_of_tool_1_does_not_spoil_tool_2() -> None:
    """Проблема «над не выше гнезда» инструмента 1 не переносится на инструмент 2."""
    checks = check_tool_points(_full_set(t1_over=_pt("t1_over", -60.0)))
    assert checks[1].ok is True
    assert checks[1].problems == ()


def test_a9_point_with_frame_is_not_in_base() -> None:
    """A9: точка ``t1_pick`` с ``frame`` не ``None`` -> у инструмента 1 проблема ``not_in_base``, не ok."""
    checks = check_tool_points(_full_set(t1_pick=_pt("t1_pick", -60.0, frame="sheet")))
    assert checks[0].problems == ("not_in_base",)
    assert checks[0].ok is False
    assert checks[1].ok is True


def test_a9_problems_follow_declared_order_not_in_base_first() -> None:
    """Обе проблемы сразу: порядок кодов - как в ``TOOL_PROBLEMS`` (``not_in_base``, затем ``over_not_above_pick``)."""
    pts = _full_set(t1_over=_pt("t1_over", -60.0), t1_exit=_pt("t1_exit", -30.0, frame="sheet"))
    checks = check_tool_points(pts)
    assert checks[0].problems == ("not_in_base", "over_not_above_pick")


def test_a9_no_points_lists_all_names_alphabetically_with_transit_for_tool_2() -> None:
    """Пустая карта: пропуски по алфавиту; у инструмента 2 в пропусках и транзитная ``t1_over``; проблем нет."""
    checks = check_tool_points({})
    assert checks[0].missing == ("t1_exit", "t1_over", "t1_pick")
    assert checks[1].missing == ("t1_over", "t2_exit", "t2_over", "t2_pick")
    assert [c.ok for c in checks] == [False, False]
    assert [c.problems for c in checks] == [(), ()]
