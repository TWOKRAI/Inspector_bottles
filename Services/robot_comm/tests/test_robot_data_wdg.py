"""Тесты автора T5.3c c2: порядок правила сторожа и ``param_bounds`` (``robot_data``).

Purpose:
    Дополняют слепую приёмку (``test_robot_data_t53c_acceptance.py``): 0 у сторожа отвергает подкласс до проверки
    границ, 0 у других параметров и не-int значения сторожа - общий ``RobotDataInvalid``, границы ``param_bounds``
    совпадают с проверкой записи.

Public API:
    Только тесты ``test_*``.

Stability: lite
"""

from __future__ import annotations

from pathlib import Path

import pytest

from Services.robot_comm.errors import RobotDataInvalid, RobotWatchdogDisabled
from Services.robot_comm.robot_data import load_params, param_bounds
from Services.robot_comm.store import RobotDataStore

TEXT_WDG = "Сторож робота нельзя выключить: P_WDG_TIMEOUT_MS = 0"


def test_wdg_zero_is_subclass_and_constant_text(tmp_path: Path) -> None:
    store = RobotDataStore(tmp_path)
    with pytest.raises(RobotWatchdogDisabled) as info:
        load_params(store, "r1", overrides={"P_WDG_TIMEOUT_MS": 0})
    assert str(info.value) == TEXT_WDG
    assert isinstance(info.value, RobotDataInvalid)
    assert info.value.rev is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"P_SPD_DEFAULT": 0}, "Данные робота не прошли проверку"),  # 0 вне границ другого параметра - общий отказ
        (
            {"P_WDG_TIMEOUT_MS": False},
            "Данные робота не прошли проверку",
        ),  # bool не int: правило сторожа не срабатывает
        ({"P_WDG_TIMEOUT_MS": 0.0}, "Данные робота не прошли проверку"),
        ({"P_WDG_TIMEOUT_MS": 60001}, "Данные робота не прошли проверку"),
    ],
)
def test_other_refusals_stay_plain_robot_data_invalid(tmp_path: Path, overrides: dict, message: str) -> None:
    with pytest.raises(RobotDataInvalid) as info:
        load_params(RobotDataStore(tmp_path), "r1", overrides=overrides)
    assert type(info.value) is RobotDataInvalid
    assert str(info.value) == message


def test_param_bounds_match_table_except_watchdog_minimum() -> None:
    assert param_bounds("P_WDG_TIMEOUT_MS") == (1, 60000)
    assert param_bounds("P_SPD_DEFAULT") == (1, 100)
    for raw in (1, 60000):
        assert load_params(RobotDataStore(Path("unused-root")), "r1", overrides={"P_WDG_TIMEOUT_MS": raw})
