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
    """СКО угла в градусах в КОДИРОВАННОМ пространстве (для совместимости/сравнения).

    Для физической ошибки (с учётом 2θ-кодирования 180-классов) используйте
    `physical_angle_errors` / `angle_report`.

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


def physical_angle_errors(
    pred_sincos: np.ndarray,
    true_sincos: np.ndarray,
    valid: np.ndarray,
    y_true: np.ndarray,
    class_symmetry: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Физическая угловая ошибка (градусы) с учётом симметрии класса.

    Кодирование dataset_gen: encoded = factor·θ, factor=2 для symmetry=180,
    иначе 1. Значит физическая ошибка = Δencoded / factor (для 180 это
    автоматически даёт диапазон [0,90] — дальше уже «другая» эквивалентная
    ориентация). full-классы должны быть исключены маской valid.

    Returns:
        (errors_deg, class_idx) — ошибки валидных сэмплов и их класс-индексы.
    """
    valid = np.asarray(valid, dtype=bool)
    if not valid.any():
        return np.empty(0), np.empty(0, dtype=np.int64)
    p = np.asarray(pred_sincos, dtype=np.float64)[valid]
    t = np.asarray(true_sincos, dtype=np.float64)[valid]
    yt = np.asarray(y_true, dtype=np.int64)[valid]
    pred_ang = np.degrees(np.arctan2(p[:, 0], p[:, 1]))
    true_ang = np.degrees(np.arctan2(t[:, 0], t[:, 1]))
    enc_diff = (pred_ang - true_ang + 180.0) % 360.0 - 180.0
    factor = np.array([2.0 if class_symmetry[c] == "180" else 1.0 for c in yt])
    return np.abs(enc_diff) / factor, yt


def angle_report(
    pred_sincos: np.ndarray,
    true_sincos: np.ndarray,
    valid: np.ndarray,
    y_true: np.ndarray,
    class_names: list[str],
    class_symmetry: list[str],
    within_deg: float = 5.0,
) -> dict[str, Any] | None:
    """Физический отчёт по углу: MAE/p95/доля≤within + разбивка none/180 + худший класс.

    Post: None, если нет валидных угловых сэмплов.
    """
    errs, yt = physical_angle_errors(pred_sincos, true_sincos, valid, y_true, class_symmetry)
    if errs.size == 0:
        return None
    report: dict[str, Any] = {
        "angle_mae_deg": round(float(errs.mean()), 2),
        "angle_p95_deg": round(float(np.percentile(errs, 95)), 2),
        f"angle_within_{within_deg:g}deg": round(float((errs <= within_deg).mean()), 4),
    }
    for sym in ("none", "180"):
        mask = np.array([class_symmetry[c] == sym for c in yt])
        if mask.any():
            report[f"angle_mae_{sym}"] = round(float(errs[mask].mean()), 2)
    # худший класс по среднему углу (где модель путает ориентацию сильнее всего)
    worst_name, worst_mae = None, -1.0
    for c in np.unique(yt):
        m = errs[yt == c].mean()
        if m > worst_mae:
            worst_name, worst_mae = class_names[c], float(m)
    report["angle_worst_class"] = {"class": worst_name, "mae_deg": round(worst_mae, 2)}
    return report


def evaluation_summary(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    class_names: list[str],
    pred_sincos: np.ndarray | None = None,
    true_sincos: np.ndarray | None = None,
    angle_valid: np.ndarray | None = None,
    class_symmetry: list[str] | None = None,
) -> dict[str, Any]:
    """Сводный отчёт: accuracy + balanced + per-class + confusion (+ угол при наличии).

    Если задан class_symmetry (симметрия по класс-индексу) — угол считается в
    ФИЗИЧЕСКИХ градусах с разбивкой none/180 и долей попадания в ±5° (то, что
    реально нужно для приёмки доворота робота). Иначе — закодированный MAE
    (обратная совместимость).
    """
    cm = confusion_matrix(y_true, y_pred, num_classes=len(class_names))
    summary: dict[str, Any] = {
        "accuracy": round(accuracy(y_true, y_pred), 4),
        "balanced_accuracy": round(balanced_accuracy(cm), 4),
        "per_class": per_class_report(cm, class_names),
        "confusion_matrix": cm.tolist(),
    }
    if pred_sincos is not None and true_sincos is not None and angle_valid is not None:
        if class_symmetry is not None:
            report = angle_report(pred_sincos, true_sincos, angle_valid, y_true, class_names, class_symmetry)
            summary.update(report or {"angle_mae_deg": None})
        else:
            mae = angle_mae_deg(pred_sincos, true_sincos, angle_valid)
            summary["angle_mae_deg"] = round(mae, 2) if mae is not None else None
    return summary
