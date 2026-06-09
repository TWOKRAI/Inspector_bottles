"""Постобработка выхода классификатора → список предсказаний.

Вход: сырой выход сети (logits или вероятности), форма (1, num_classes) или (num_classes,).
Выход: list[dict] топ-K классов с confidence ≥ порога.

Формат предсказания (dict-at-boundary, pickle-safe для pipeline):
    {"class_id": int, "label": str, "confidence": float}
"""

from __future__ import annotations

import numpy as np


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
