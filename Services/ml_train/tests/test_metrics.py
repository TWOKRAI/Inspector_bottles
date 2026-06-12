"""Метрики: проверка на известных вручную значениях (без torch/sklearn)."""

import numpy as np
import pytest

from Services.ml_train import metrics as M


def test_confusion_matrix_known():
    cm = M.confusion_matrix(np.array([0, 0, 1, 1, 2]), np.array([0, 1, 1, 1, 0]), 3)
    assert cm.tolist() == [[1, 1, 0], [0, 2, 0], [1, 0, 0]]


def test_accuracy_and_balanced():
    y_true = np.array([0, 0, 0, 0, 1])
    y_pred = np.array([0, 0, 0, 0, 0])
    assert M.accuracy(y_true, y_pred) == pytest.approx(0.8)
    cm = M.confusion_matrix(y_true, y_pred, 2)
    # recall: класс 0 → 1.0, класс 1 → 0.0 → balanced = 0.5 (а accuracy 0.8)
    assert M.balanced_accuracy(cm) == pytest.approx(0.5)


def test_balanced_ignores_empty_classes():
    cm = M.confusion_matrix(np.array([0, 0]), np.array([0, 0]), 3)
    assert M.balanced_accuracy(cm) == pytest.approx(1.0)


def test_per_class_report():
    cm = M.confusion_matrix(np.array([0, 0, 1]), np.array([0, 1, 1]), 2)
    rows = M.per_class_report(cm, ["a", "b"])
    assert rows[0]["precision"] == 1.0 and rows[0]["recall"] == 0.5
    assert rows[1]["support"] == 1


def test_angle_mae_wraparound():
    # 350° vs 10° → ошибка 20°, не 340°
    pred = np.array([[np.sin(np.radians(350)), np.cos(np.radians(350))]])
    true = np.array([[np.sin(np.radians(10)), np.cos(np.radians(10))]])
    mae = M.angle_mae_deg(pred, true, np.array([True]))
    assert mae == pytest.approx(20.0, abs=1e-6)


def test_angle_mae_respects_mask():
    pred = np.array([[0.0, 1.0], [1.0, 0.0]])
    true = np.array([[0.0, 1.0], [0.0, 1.0]])
    # второй сэмпл (ошибка 90°) замаскирован → MAE = 0
    assert M.angle_mae_deg(pred, true, np.array([True, False])) == pytest.approx(0.0)
    assert M.angle_mae_deg(pred, true, np.array([False, False])) is None


def test_evaluation_summary_keys():
    s = M.evaluation_summary(np.array([0, 1]), np.array([0, 1]), ["a", "b"])
    assert s["accuracy"] == 1.0
    assert "confusion_matrix" in s and "per_class" in s
    assert "angle_mae_deg" not in s
