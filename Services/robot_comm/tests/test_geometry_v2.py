"""RED: независимые приёмочные тесты для SCARA-геометрии (T2.0, protocol-spec §7.3).

Модуль `Services.robot_comm.programs.geometry` ещё не существует — импорт
намеренно вынесен в фикстуру `geometry`, чтобы сбор тестов (collection) не
падал целиком, а каждый тест падал по отдельности с ModuleNotFoundError.

Контракт (продиктован лидом, не выведен из кода):
- Workspace(frozen dataclass) + Workspace.from_params(mapping P_WS_*)
- check_point(ws, x, y, z, rz) -> int: 0 или 4 (R_OUT_OF_ZONE)
- check_segment(ws, x0, y0, x1, y1) -> int: 0, 4 или 5 (R_DEAD_ZONE)
- Frame(frozen dataclass) + Frame.from_points(origin, on_x, in_plane)
- frame.to_base(x, y, z, rz) / frame.from_base(x, y, z, rz) — взаимно обратные

Тестовое рабочее пространство (дефолты delta_v2.yaml, scale 10):
r_min=100, r_max=600, z=[-150, 0], rz=[-360, 360], sector=[-165, 165] deg,
box_en=False, box x/y = [-600, 600].
"""

from __future__ import annotations

import math

import pytest


@pytest.fixture
def geometry():
    from Services.robot_comm.programs import geometry as geometry_module

    return geometry_module


@pytest.fixture
def ws(geometry):
    """Боевое рабочее пространство из брифа лида (box выключен)."""
    return geometry.Workspace(
        r_min=100.0,
        r_max=600.0,
        z_min=-150.0,
        z_max=0.0,
        rz_min=-360.0,
        rz_max=360.0,
        ang_min=-165.0,
        ang_max=165.0,
        box_en=False,
        x_min=-600.0,
        x_max=600.0,
        y_min=-600.0,
        y_max=600.0,
    )


# ---------------------------------------------------------------------------
# Workspace.from_params
# ---------------------------------------------------------------------------


def test_from_params_maps_names(geometry):
    values = {
        "P_WS_R_MIN": 100.0,
        "P_WS_R_MAX": 600.0,
        "P_WS_Z_MIN": -150.0,
        "P_WS_Z_MAX": 0.0,
        "P_WS_RZ_MIN": -360.0,
        "P_WS_RZ_MAX": 360.0,
        "P_WS_ANG_MIN": -165.0,
        "P_WS_ANG_MAX": 165.0,
        "P_WS_BOX_EN": 1.0,
        "P_WS_X_MIN": -600.0,
        "P_WS_X_MAX": 600.0,
        "P_WS_Y_MIN": -600.0,
        "P_WS_Y_MAX": 600.0,
    }

    result = geometry.Workspace.from_params(values)

    assert result.r_min == 100.0
    assert result.r_max == 600.0
    assert result.z_min == -150.0
    assert result.z_max == 0.0
    assert result.rz_min == -360.0
    assert result.rz_max == 360.0
    assert result.ang_min == -165.0
    assert result.ang_max == 165.0
    assert result.box_en is True
    assert result.x_min == -600.0
    assert result.x_max == 600.0
    assert result.y_min == -600.0
    assert result.y_max == 600.0

    # box_en: 0 -> False (nonzero -> True per DESIGN)
    values_off = dict(values, P_WS_BOX_EN=0.0)
    result_off = geometry.Workspace.from_params(values_off)
    assert result_off.box_en is False


# ---------------------------------------------------------------------------
# check_point
# ---------------------------------------------------------------------------

POINT_VIOLATIONS = [
    pytest.param(0.0, 0.0, -50.0, 0.0, id="inside_ring_hole_origin"),
    pytest.param(50.0, 0.0, -50.0, 0.0, id="inside_ring_hole_50"),
    pytest.param(700.0, 0.0, -50.0, 0.0, id="beyond_r_max"),
    pytest.param(300.0, 0.0, -200.0, 0.0, id="z_below_min"),
    pytest.param(300.0, 0.0, 50.0, 0.0, id="z_above_max"),
    pytest.param(300.0, 0.0, -50.0, -400.0, id="rz_below_min"),
    pytest.param(300.0, 0.0, -50.0, 400.0, id="rz_above_max"),
    pytest.param(-300.0, 0.0, -50.0, 0.0, id="behind_sector"),
]


@pytest.mark.parametrize("x, y, z, rz", POINT_VIOLATIONS)
def test_point_each_violation_is_reason_4(geometry, ws, x, y, z, rz):
    assert geometry.check_point(ws, x, y, z, rz) == 4


def test_point_bounds_inclusive(geometry, ws):
    # r ring: ровно r_min и ровно r_max
    assert geometry.check_point(ws, 100.0, 0.0, -50.0, 0.0) == 0
    assert geometry.check_point(ws, 600.0, 0.0, -50.0, 0.0) == 0
    # z: ровно границы
    assert geometry.check_point(ws, 300.0, 0.0, -150.0, 0.0) == 0
    assert geometry.check_point(ws, 300.0, 0.0, 0.0, 0.0) == 0
    # rz: ровно границы
    assert geometry.check_point(ws, 300.0, 0.0, -50.0, -360.0) == 0
    assert geometry.check_point(ws, 300.0, 0.0, -50.0, 360.0) == 0
    # сектор: ровно на границах -165/165 град (проверено вручную: round-trip
    # cos/sin -> atan2 -> degrees точно возвращает -165.0/165.0 в IEEE754,
    # никакого допуска не требуется)
    r = 300.0
    x_min_edge = r * math.cos(math.radians(-165.0))
    y_min_edge = r * math.sin(math.radians(-165.0))
    x_max_edge = r * math.cos(math.radians(165.0))
    y_max_edge = r * math.sin(math.radians(165.0))
    assert geometry.check_point(ws, x_min_edge, y_min_edge, -50.0, 0.0) == 0
    assert geometry.check_point(ws, x_max_edge, y_max_edge, -50.0, 0.0) == 0
    # box: ровно на границах (box_en=True, отдельное пространство)
    ws_box = geometry.Workspace(
        r_min=100.0,
        r_max=600.0,
        z_min=-150.0,
        z_max=0.0,
        rz_min=-360.0,
        rz_max=360.0,
        ang_min=-165.0,
        ang_max=165.0,
        box_en=True,
        x_min=-200.0,
        x_max=200.0,
        y_min=-200.0,
        y_max=200.0,
    )
    assert geometry.check_point(ws_box, 200.0, 150.0, -50.0, 0.0) == 0  # x на x_max
    assert geometry.check_point(ws_box, 100.0, -200.0, -50.0, 0.0) == 0  # y на y_min


def test_box_ignored_when_disabled(geometry):
    kwargs = dict(
        r_min=100.0,
        r_max=600.0,
        z_min=-150.0,
        z_max=0.0,
        rz_min=-360.0,
        rz_max=360.0,
        ang_min=-165.0,
        ang_max=165.0,
        x_min=-200.0,
        x_max=200.0,
        y_min=-200.0,
        y_max=200.0,
    )
    ws_off = geometry.Workspace(box_en=False, **kwargs)
    ws_on = geometry.Workspace(box_en=True, **kwargs)

    # x=300,y=0: r=300 (в кольце), угол=0 (в секторе), но x=300 вне бокса x_max=200
    assert geometry.check_point(ws_off, 300.0, 0.0, -50.0, 0.0) == 0
    assert geometry.check_point(ws_on, 300.0, 0.0, -50.0, 0.0) == 4


# ---------------------------------------------------------------------------
# check_segment
# ---------------------------------------------------------------------------


def test_segment_through_dead_zone_is_5(geometry, ws):
    # линия y=50: ближайшая к началу координат точка (0,50), dist=50 < r_min=100
    assert geometry.check_segment(ws, -300.0, 50.0, 300.0, 50.0) == 5


def test_segment_tangent_at_r_min_allowed(geometry, ws):
    # линия y=100: ближайшая точка (0,100), dist=100 == r_min ровно -> допустимо
    # оба конца валидны по сектору: углы 161.57 град и 18.43 град (внутри ±165)
    assert geometry.check_segment(ws, -300.0, 100.0, 300.0, 100.0) == 0


def test_segment_through_forbidden_sector_is_4(geometry, ws):
    # x=-300 фиксирован, y от 200 до -200: пересекает угол 180/-180,
    # оба конца внутри сектора (±146.31 град), но середина (около y=0) — нет.
    # min dist до начала координат = 300 (>= r_min) -> не dead zone.
    assert geometry.check_segment(ws, -300.0, 200.0, -300.0, -200.0) == 4


def test_segment_short_inside_sector_allowed(geometry, ws):
    # короткий отрезок целиком в секторе и вдали от мёртвой зоны
    assert geometry.check_segment(ws, 300.0, 0.0, 310.0, 5.0) == 0
    # нулевой длины
    assert geometry.check_segment(ws, 300.0, 0.0, 300.0, 0.0) == 0


# ---------------------------------------------------------------------------
# Frame
# ---------------------------------------------------------------------------

FRAMES = [
    pytest.param((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (0.0, 100.0, 0.0), id="identity_like"),
    pytest.param((100.0, 200.0, -50.0), (100.0, 300.0, -50.0), (0.0, 200.0, -50.0), id="known_transform_frame"),
    pytest.param((10.0, 20.0, 30.0), (10.0, 20.0, 130.0), (10.0, 120.0, 30.0), id="x_along_base_z"),
    pytest.param((5.0, -5.0, 0.0), (55.0, 45.0, 20.0), (5.0, 45.0, 60.0), id="tilted_plane"),
]

LOCAL_POINTS = [
    (0.0, 0.0, 0.0, 0.0),
    (10.0, 0.0, 0.0, 0.0),
    (0.0, 10.0, 0.0, 90.0),
    (-25.0, 40.0, 15.0, -30.0),
    (123.456, -78.9, 3.21, 179.0),
]


@pytest.mark.parametrize("origin, on_x, in_plane", FRAMES)
def test_frame_round_trip_identity(geometry, origin, on_x, in_plane):
    frame = geometry.Frame.from_points(origin, on_x, in_plane)

    for x, y, z, rz in LOCAL_POINTS:
        base = frame.to_base(x, y, z, rz)
        local_back = frame.from_base(*base)
        assert local_back[0] == pytest.approx(x, abs=1e-9)
        assert local_back[1] == pytest.approx(y, abs=1e-9)
        assert local_back[2] == pytest.approx(z, abs=1e-9)
        assert local_back[3] == pytest.approx(rz, abs=1e-9)

        base_back = frame.to_base(*local_back)
        assert base_back[0] == pytest.approx(base[0], abs=1e-9)
        assert base_back[1] == pytest.approx(base[1], abs=1e-9)
        assert base_back[2] == pytest.approx(base[2], abs=1e-9)
        assert base_back[3] == pytest.approx(base[3], abs=1e-9)


def test_frame_known_transform(geometry):
    # Литералы посчитаны вручную (см. отчёт), НЕ через код фрейма:
    # origin=(100,200,-50), on_x=(100,300,-50) -> X=(0,1,0)
    # in_plane=(0,200,-50) -> in_plane-origin=(-100,0,0)
    # Z = normalize(X x (in_plane-origin)) = normalize((0,0,100)) = (0,0,1)
    # Y = Z x X = (0,0,1) x (0,1,0) = (-1,0,0)
    # yaw = degrees(atan2(X.y, X.x)) = atan2(1,0) = 90
    frame = geometry.Frame.from_points((100.0, 200.0, -50.0), (100.0, 300.0, -50.0), (0.0, 200.0, -50.0))

    base1 = frame.to_base(10.0, 0.0, 0.0, 0.0)
    assert base1[0] == pytest.approx(100.0, abs=1e-9)
    assert base1[1] == pytest.approx(210.0, abs=1e-9)
    assert base1[2] == pytest.approx(-50.0, abs=1e-9)
    assert base1[3] == pytest.approx(90.0, abs=1e-9)

    base2 = frame.to_base(0.0, 10.0, 0.0, 0.0)
    assert base2[0] == pytest.approx(90.0, abs=1e-9)
    assert base2[1] == pytest.approx(200.0, abs=1e-9)
    assert base2[2] == pytest.approx(-50.0, abs=1e-9)
    assert base2[3] == pytest.approx(90.0, abs=1e-9)


def test_frame_degenerate_raises(geometry):
    origin = (0.0, 0.0, 0.0)
    # on_x на расстоянии 0.5 мм от origin (< 1 мм)
    with pytest.raises(ValueError):
        geometry.Frame.from_points(origin, (0.0005, 0.0, 0.0), (0.0, 1.0, 0.0))
    # in_plane на расстоянии 0.5 мм от линии оси X (сама точка далеко от origin)
    with pytest.raises(ValueError):
        geometry.Frame.from_points(origin, (10.0, 0.0, 0.0), (5.0, 0.0005, 0.0))
