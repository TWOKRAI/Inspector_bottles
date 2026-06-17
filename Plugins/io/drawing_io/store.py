"""Чистое сохранение/загрузка карты точек рисунка: JSON (+ опц. PNG рядом).

Без зависимостей от плагина/фреймворка (тестируется напрямую). JSON хранит точки в
мм, границы листа и метаданные; PNG — кадр-референс рядом (тот же stem). Загрузка —
обратная операция: точки/границы/мета + путь к PNG (если есть).
"""

from __future__ import annotations

import json
import os
from typing import Any

import cv2
import numpy as np

SCHEMA_VERSION = 1


def _coerce_points(points: list[dict]) -> list[dict]:
    """Привести точки к чистому виду {x_mm, y_mm, pen} (float/int)."""
    out: list[dict] = []
    for p in points:
        if not isinstance(p, dict) or "x_mm" not in p or "y_mm" not in p:
            continue
        out.append({"x_mm": float(p["x_mm"]), "y_mm": float(p["y_mm"]), "pen": int(p.get("pen", 1))})
    return out


def save(
    dirpath: str,
    stem: str,
    points: list[dict],
    *,
    bounds: list[float] | None = None,
    meta: dict[str, Any] | None = None,
    image_bgr: np.ndarray | None = None,
) -> str:
    """Сохранить рисунок: ``dir/stem.json`` (+ ``dir/stem.png``, если есть image_bgr).

    Возвращает путь к JSON. Каталог создаётся при необходимости.
    """
    os.makedirs(dirpath, exist_ok=True)
    json_path = os.path.join(dirpath, f"{stem}.json")
    png_path = os.path.join(dirpath, f"{stem}.png")

    pts = _coerce_points(points)
    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "points": pts,
        "bounds": list(bounds) if bounds is not None else None,
        "meta": dict(meta or {}),
        "image": None,
    }
    image_ok = image_bgr is not None and hasattr(image_bgr, "shape")
    if image_ok and cv2.imwrite(png_path, image_bgr):
        payload["image"] = os.path.basename(png_path)

    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return json_path


def load(json_path: str) -> tuple[list[dict], list[float] | None, dict[str, Any], str | None]:
    """Загрузить рисунок из JSON → (points, bounds, meta, image_path|None).

    image_path абсолютен (рядом с JSON), если PNG записан и существует.
    """
    with open(json_path, encoding="utf-8") as fh:
        data = json.load(fh)
    points = _coerce_points(list(data.get("points") or []))
    bounds = data.get("bounds")
    bounds = [float(v) for v in bounds] if isinstance(bounds, list) and len(bounds) == 4 else None
    meta = dict(data.get("meta") or {})
    image_path: str | None = None
    img_name = data.get("image")
    if img_name:
        cand = os.path.join(os.path.dirname(os.path.abspath(json_path)), img_name)
        if os.path.exists(cand):
            image_path = cand
    return points, bounds, meta, image_path
