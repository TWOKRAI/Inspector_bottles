"""Метрики классификации и угла — чистый numpy (без sklearn).

Все функции принимают плоские массивы предсказаний/меток за весь датасет.
Используются трейнером для history/metrics.json и реестром прогонов для сравнения.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def confusion_matrix(y_true: np.ndarray, y_pred: np.ndarray, num_classes: int) -> np.ndarray:
    """Матрица ошибок (num_classes x num_classes): строки — истина, столбцы — предсказание.

    Pre: значения y_true/y_pred в [0, num_classes).
    """
    y_true = np.asarray(y_true, dtype=np.int64)
    y_pred = np.asarray(y_pred, dtype=np.int64)
    cm = np.zeros((num_classes, num_classes), dtype=np.int64)
    np.add.at(cm, (y_true, y_pred), 1)
    return cm


def accuracy(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """Доля верных предсказаний."""
    y_true = np.asarray(y_true)
    if y_true.size == 0:
        return 0.0
    return float((y_true == np.asarray(y_pred)).mean())


def balanced_accuracy(cm: np.ndarray) -> float:
    """Средний recall по классам (устойчива к дисбалансу). Классы без примеров игнорируются."""
    support = cm.sum(axis=1)
    mask = support > 0
    if not mask.any():
        return 0.0
    recall = cm.diagonal()[mask] / support[mask]
    return float(recall.mean())


def per_class_report(cm: np.ndarray, class_names: list[str]) -> list[dict[str, Any]]:
    """precision/recall/f1/support по каждому классу (аналог classification_report)."""
    rows: list[dict[str, Any]] = []
    diag = cm.diagonal().astype(np.float64)
    pred_total = cm.sum(axis=0).astype(np.float64)
    true_total = cm.sum(axis=1).astype(np.float64)
    for i, name in enumerate(class_names):
        precision = diag[i] / pred_total[i] if pred_total[i] > 0 else 0.0
        recall = diag[i] / true_total[i] if true_total[i] > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        rows.append(
            {
                "class": name,
                "precision": round(float(precision), 4),
                "recall": round(float(recall), 4),
                "f1": round(float(f1), 4),
                "support": int(true_total[i]),
            }
        )
    return rows


def angle_mae_deg(
    pred_sincos: np.ndarray,
    true_sincos: np.ndarray,
    valid: np.ndarray,
) -> float | None:
    """Средняя абсолютная угловая ошибка в градусах (в КОДИРОВАННОМ пространстве угла).

    Для классов с symmetry=180 dataset_gen кодирует 2θ — физическая ошибка
    вдвое меньше показанной; метрика едина для всех классов и пригодна
    для сравнения прогонов.

    Pre: pred/true — (N, 2) [sin, cos]; valid — (N,) bool маска.
    Post: None, если валидных сэмплов нет.
    """
    valid = np.asarray(valid, dtype=bool)
    if not valid.any():
        return None
    p = np.asarray(pred_sincos, dtype=np.float64)[valid]
    t = np.asarray(true_sincos, dtype=np.float64)[valid]
    pred_ang = np.degrees(np.arctan2(p[:, 0], p[:, 1]))
    true_ang = np.degrees(np.arctan2(t[:, 0], t[:, 1]))
    diff = (pred_ang - true_ang + 180.0) % 360.0 - 180.0
    return float(np.abs(diff).mean())


def evaluation_summary(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    class_names: list[str],
    pred_sincos: np.ndarray | None = None,
    true_sincos: np.ndarray | None = None,
    angle_valid: np.ndarray | None = None,
) -> dict[str, Any]:
    """Сводный отчёт: accuracy + balanced + per-class + confusion (+ угол при наличии)."""
    cm = confusion_matrix(y_true, y_pred, num_classes=len(class_names))
    summary: dict[str, Any] = {
        "accuracy": round(accuracy(y_true, y_pred), 4),
        "balanced_accuracy": round(balanced_accuracy(cm), 4),
        "per_class": per_class_report(cm, class_names),
        "confusion_matrix": cm.tolist(),
    }
    if pred_sincos is not None and true_sincos is not None and angle_valid is not None:
        mae = angle_mae_deg(pred_sincos, true_sincos, angle_valid)
        summary["angle_mae_deg"] = round(mae, 2) if mae is not None else None
    return summary
