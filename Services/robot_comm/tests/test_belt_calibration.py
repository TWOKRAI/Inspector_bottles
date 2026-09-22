# -*- coding: utf-8 -*-
"""RED-приёмка Task 2.3a — ``BeltDrive.set_calibration`` (line-sim Ф2 «правда ленты»).

Независимый tester, worktree на коммите ДО реализации (``4aa2a8c3``). Контракт —
ТОЛЬКО из блока REDS Task 2.3a плана (``plans/line-sim/phase-2-belt-truth.md``):
``set_calibration`` и свойства ``mm_s_at_max_freq``/``state`` на ``BeltDrive`` ещё
не существуют — ожидаемый провал ``AttributeError``.
"""

from __future__ import annotations

import pytest

from Services.robot_comm.server.belt import BeltDrive


def test_set_calibration_rescales_running_belt() -> None:
    """REDS 1: лента едет на 25 Гц (мм/с=50 при калибровке по умолчанию 100),
    рекалибровка на 200 мм/с@max пересчитывает текущую скорость на новую шкалу."""
    belt = BeltDrive()
    belt.command(True, 25)
    belt.set_calibration(200.0)
    assert belt.mm_s == pytest.approx(100.0)


def test_set_calibration_leaves_raw_mode_at_max_freq() -> None:
    """REDS 2: рекалибровка «сырой» (from_enc_rate) ленты выводит её из сырого
    режима так, будто пришла команда run=True на максимальной частоте."""
    belt = BeltDrive.from_enc_rate(7, 0.01)
    belt.set_calibration(200.0)
    assert belt.mm_s == pytest.approx(200.0)
    assert belt.state == {"run": True, "freq_hz": 50.0, "reverse": False}


def test_set_calibration_rejects_negative_and_nan() -> None:
    """REDS 3: отрицательная и NaN калибровка — ValueError, калибровка не меняется."""
    belt = BeltDrive()
    before = belt.mm_s_at_max_freq

    with pytest.raises(ValueError):
        belt.set_calibration(-1.0)
    assert belt.mm_s_at_max_freq == before

    with pytest.raises(ValueError):
        belt.set_calibration(float("nan"))
    assert belt.mm_s_at_max_freq == before
