"""Авторские проверки: Z системы координат всегда вверх; NaN/inf не проходят как «разрешено»."""

import math

import pytest

from Services.robot_comm.programs.geometry import Frame, Workspace, check_segment

_WS = Workspace(
    r_min=100, r_max=600, z_min=-150, z_max=0, rz_min=-360, rz_max=360,
    ang_min=-165, ang_max=165, box_en=False, x_min=-600, x_max=600, y_min=-600, y_max=600,
)


@pytest.mark.parametrize("third", [(300, 100, -100), (300, -100, -100)])
def test_frame_z_points_up_whichever_side_the_third_point(third: tuple[float, float, float]) -> None:
    f = Frame.from_points((300, 0, -100), (400, 0, -100), third)
    x, y, z, rz = f.to_base(0, 0, 50, 10)
    assert z == pytest.approx(-50)  # на 50 мм НАД плоскостью листа
    assert rz == pytest.approx(10)  # ось X совпадает с базовой — поворот не меняется


def test_nan_frame_rejected() -> None:
    with pytest.raises(ValueError):
        Frame.from_points((math.nan, 0, 0), (400, 0, -100), (300, 100, -100))


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_non_finite_segment_is_out_of_zone(bad: float) -> None:
    assert check_segment(_WS, 200, 0, bad, 0) == 4
