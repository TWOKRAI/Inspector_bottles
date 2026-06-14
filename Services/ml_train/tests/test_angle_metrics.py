"""Физические угловые метрики (градусы, per-symmetry, доля ≤5°) + hold-out helpers."""

from __future__ import annotations

import numpy as np

from Services.dataset_gen.core.symmetry import encode_angle
from Services.ml_train.holdout_eval import _angle_error
from Services.ml_train.metrics import angle_report, physical_angle_errors


def _enc(deg: float, sym: str) -> list[float]:
    s, c, _ = encode_angle(deg, sym)
    return [s, c]


def test_physical_mae_equal_for_none_and_180() -> None:
    """Ошибка 3° физически = 3° и для none, и для 180 (а закодированно у 180 было бы 6°)."""
    names, sym = ["A", "N"], ["none", "180"]
    preds, trues, valid, yt = [], [], [], []
    for cls, s in enumerate(sym):
        for deg in (10, 40, 100, 200, 300):
            preds.append(_enc(deg + 3, s))
            trues.append(_enc(deg, s))
            valid.append(True)
            yt.append(cls)
    r = angle_report(np.array(preds), np.array(trues), np.array(valid), np.array(yt), names, sym)
    assert abs(r["angle_mae_deg"] - 3.0) < 0.3
    assert abs(r["angle_mae_none"] - 3.0) < 0.3
    assert abs(r["angle_mae_180"] - 3.0) < 0.3
    assert r["angle_within_5deg"] == 1.0


def test_physical_errors_skip_invalid() -> None:
    """full-классы (valid=False) исключены из угловой ошибки."""
    errs, yt = physical_angle_errors(
        np.array([[0.0, 1.0], [0.0, 1.0]]),
        np.array([[0.0, 1.0], [1.0, 0.0]]),
        np.array([True, False]),
        np.array([0, 0]),
        ["none"],
    )
    assert errs.size == 1  # второй (invalid) отброшен


def test_within_5deg_fraction() -> None:
    names, sym = ["A"], ["none"]
    preds = [_enc(10, "none"), _enc(10, "none"), _enc(100, "none")]
    trues = [_enc(12, "none"), _enc(50, "none"), _enc(101, "none")]  # ошибки 2,40,1
    r = angle_report(np.array(preds), np.array(trues), np.array([True] * 3), np.array([0] * 3), names, sym)
    assert abs(r["angle_within_5deg"] - 2 / 3) < 1e-3  # 2 из 3 в пределах 5° (округл. до 4 зн.)


def test_holdout_angle_error_period() -> None:
    """Угловая ошибка hold-out учитывает период симметрии (180 для 180-букв)."""
    assert _angle_error(10.0, 190.0, "180") < 1e-6  # 10° и 190° тождественны при 180
    assert abs(_angle_error(10.0, 190.0, "none") - 180.0) < 1e-6
    assert abs(_angle_error(350.0, 5.0, "none") - 15.0) < 1e-6  # через 0°
