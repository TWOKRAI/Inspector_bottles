"""Авторская проверка: радиальный ход наружу от оси J1 допустим.

Прямая такого отрезка проходит через (0, 0), но сам отрезок — нет. Без ограничения параметра проекции
отрезком [0, 1] ближайшей бралась бы точка продолжения прямой, и законный ход «от оси наружу»
отклонялся бы как проход через мёртвую зону.
"""

import pytest

from Services.robot_comm.programs.geometry import Workspace, check_segment

_WS = Workspace(
    r_min=100, r_max=600, z_min=-150, z_max=0, rz_min=-360, rz_max=360,
    ang_min=-165, ang_max=165, box_en=False, x_min=-600, x_max=600, y_min=-600, y_max=600,
)


@pytest.mark.parametrize("seg", [(200, 0, 400, 0), (400, 0, 200, 0), (0, 150, 0, 500)])
def test_radial_segment_outside_dead_zone_allowed(seg: tuple[float, float, float, float]) -> None:
    assert check_segment(_WS, *seg) == 0
