"""Авторская проверка: to_raw округляет до ближайшего (половина — от нуля), а не отсекает.

Круговой тест сырое → инженерное → сырое этого не видит: на целых сырых значениях отсечка и округление
совпадают. Отсечка сдвигала бы введённую в GUI координату на 0.1 мм к нулю.
"""

import pytest

from Services.robot_comm.core.params_v2 import to_raw


@pytest.mark.parametrize(
    "name,eng,raw",
    [
        ("P_HOME_X", 300.06, 3001),  # 3000.6 → 3001, отсечка дала бы 3000
        ("P_HOME_Y", -210.06, -2101),  # −2100.6 → −2101, отсечка дала бы −2100
        ("P_HOME_X", 300.04, 3000),
        ("P_SPD_DEFAULT", 79.6, 80),  # scale 1
    ],
)
def test_to_raw_rounds_to_nearest(name: str, eng: float, raw: int) -> None:
    assert to_raw(name, eng) == raw
