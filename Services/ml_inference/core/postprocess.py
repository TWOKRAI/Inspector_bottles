"""Постобработка выхода классификатора → список предсказаний.

Вход: сырой выход сети (logits или вероятности), форма (1, num_classes) или (num_classes,).
Выход: list[dict] топ-K классов с confidence ≥ порога.

Формат предсказания (dict-at-boundary, pickle-safe для pipeline):
    {"class_id": int, "label": str, "confidence": float}
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

SymmetryType = Literal["none", "180", "full"]


def decode_angle(sin_v: float, cos_v: float, symmetry: SymmetryType) -> tuple[float, bool]:
    """(sin, cos) выхода angle-головы → физический угол с учётом симметрии.

    ЗЕРКАЛО dataset_gen.encode_angle (паритет проверяется контракт-тестом
    test_postprocess). atan2 масштабо-инвариантен → нормировать (sin,cos) не нужно.

    Post:
      - none: angle_deg ∈ [0,360), valid=True;
      - 180:  angle_deg ∈ [0,180), valid=True (θ и θ+180° неразличимы);
      - full: (0.0, False) — угол не определён, доворот не нужен.
    """
    if symmetry == "full":
        return 0.0, False
    raw_deg = math.degrees(math.atan2(sin_v, cos_v))
    period = 180.0 if symmetry == "180" else 360.0
    deg = (raw_deg / 2.0 if symmetry == "180" else raw_deg) % period
    if deg > period - 1e-6:  # граничный шум float (≈period → 0)
        deg = 0.0
    return deg, True


def angle_postprocess(angle_raw: np.ndarray, symmetry: SymmetryType = "none") -> dict:
    """Выход angle-головы (1,2)|(2,) [sin,cos] → {angle_deg, angle_valid}."""
    arr = np.asarray(angle_raw, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr[0]
    if arr.ndim != 1 or arr.shape[0] < 2:
        raise ValueError(f"ожидается выход угла (1,2) или (2,), получено {angle_raw.shape}")
    deg, valid = decode_angle(float(arr[0]), float(arr[1]), symmetry)
    return {"angle_deg": deg, "angle_valid": valid}


def softmax(logits: np.ndarray) -> np.ndarray:
    """Численно стабильный softmax по последней оси."""
    x = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(x)
    return exp / np.sum(exp, axis=-1, keepdims=True)


def classify_postprocess(
    raw: np.ndarray,
    *,
    labels: list[str] | None = None,
    top_k: int = 5,
    threshold: float = 0.0,
    apply_softmax: bool = True,
) -> list[dict]:
    """Сырой выход → топ-K предсказаний с порогом.

    Args:
        raw: выход сети, (1, N) или (N,).
        labels: имена классов; None → "class_<id>".
        top_k: сколько верхних классов вернуть.
        threshold: минимальная confidence (0..1) для включения.
        apply_softmax: True если raw = logits; False если уже вероятности.

    Returns:
        list[dict] отсортированный по убыванию confidence.
    """
    arr = np.asarray(raw, dtype=np.float32)
    if arr.ndim == 2:
        arr = arr[0]
    if arr.ndim != 1:
        raise ValueError(f"ожидается выход (1, N) или (N,), получено {raw.shape}")

    probs = softmax(arr) if apply_softmax else arr

    k = max(1, min(top_k, probs.shape[0]))
    # argpartition для top-K, затем сортировка только top-K (быстрее full argsort).
    top_idx = np.argpartition(probs, -k)[-k:]
    top_idx = top_idx[np.argsort(probs[top_idx])[::-1]]

    results: list[dict] = []
    for idx in top_idx:
        conf = float(probs[idx])
        if conf < threshold:
            continue
        cid = int(idx)
        label = labels[cid] if labels is not None and cid < len(labels) else f"class_{cid}"
        results.append({"class_id": cid, "label": label, "confidence": conf})
    return results
