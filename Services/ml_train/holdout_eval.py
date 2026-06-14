"""Валидация модели на РЕАЛЬНОМ hold-out — честная приёмка перед выставкой.

Зачем: train/val синтетика из тех же 4 спрайтов меряет переобучение на
синтетику, а не реальный домен. Этот модуль гоняет ЭКСПОРТИРОВАННУЮ модель
через продакшн-путь Services.ml_inference на реальных фото со сцены и считает
то, что важно роботу: точность буквы + ФИЗИЧЕСКУЮ угловую ошибку + долю ≤5°.

Раскладка hold-out (как у real_photos, но это ДРУГИЕ кадры — не из обучения):
    <holdout>/<буква>/<угол>.jpg   (угол = поворот буквы CCW, 0..359)

Путь кадра = как в проде: детекция диска (HoughCircles) → квадратный кроп →
engine.predict (sidecar сам делает resize/normalize). Тем самым заодно
проверяется весь инференс-контракт на реальных изображениях.

Запуск:
    python -m Services.ml_train eval <model_id> <holdout_dir> [--models-dir data/models]
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import imread_unicode
from Services.dataset_gen.core.realcut import detect_disk
from Services.ml_inference.engine import InferenceEngine

logger = logging.getLogger(__name__)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def _angle_from_name(stem: str) -> float | None:
    nums = re.findall(r"\d+", stem)
    return float(nums[-1]) % 360.0 if nums else None


def _crop_disk(bgr: np.ndarray, margin: float) -> np.ndarray:
    """КВАДРАТНЫЙ кроп вокруг диска (сторона 2r·(1+margin)).

    Квадрат обязателен: при resize_policy=stretch прямоугольный кроп растянул бы
    диск и сдвинул угол. У края кадра недостающие поля достраиваются репликацией
    края (тёмно-синий фон реплицируется в тёмно-синий — без чёрной рамки).
    """
    h, w = bgr.shape[:2]
    cx, cy, r = detect_disk(bgr)
    half = int(round(r * (1.0 + margin)))
    sx0, sy0 = max(0, cx - half), max(0, cy - half)
    sx1, sy1 = min(w, cx + half), min(h, cy + half)
    crop = bgr[sy0:sy1, sx0:sx1]
    top, left = sy0 - (cy - half), sx0 - (cx - half)
    bottom, right = 2 * half - (top + crop.shape[0]), 2 * half - (left + crop.shape[1])
    if any(b > 0 for b in (top, bottom, left, right)):
        crop = cv2.copyMakeBorder(crop, top, max(0, bottom), left, max(0, right), cv2.BORDER_REPLICATE)
    return crop


def _angle_error(pred_deg: float, true_deg: float, symmetry: str) -> float:
    """Физическая угловая ошибка с учётом периода симметрии (180/360)."""
    period = 180.0 if symmetry == "180" else 360.0
    d = abs(pred_deg - (true_deg % period)) % period
    return min(d, period - d)


def evaluate_holdout(
    model_id: str,
    holdout_dir: str | Path,
    models_dir: str | Path = "data/models",
    device: str = "cpu",
    margin: float = 0.18,
    within_deg: float = 5.0,
) -> dict[str, Any]:
    """Прогнать модель по hold-out, вернуть сводку (и залогировать таблицу)."""
    engine = InferenceEngine(str(models_dir))
    engine.load_model(model_id, device=device)
    sym_map = engine._spec.symmetry if engine._spec else {}

    root = Path(holdout_dir)
    letter_dirs = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith((".", "_")))
    if not letter_dirs:
        raise SystemExit(f"В {root} нет подпапок-букв")

    total = correct = 0
    ang_errors: list[float] = []
    per_letter: dict[str, dict[str, Any]] = {}

    for letter_dir in letter_dirs:
        letter = letter_dir.name
        pl = per_letter.setdefault(letter, {"n": 0, "ok": 0, "ang": []})
        for img in sorted(p for p in letter_dir.iterdir() if p.suffix.lower() in _IMAGE_SUFFIXES):
            true_angle = _angle_from_name(img.stem)
            bgr = imread_unicode(img)
            preds = engine.predict(_crop_disk(bgr, margin), top_k=1)
            if not preds:
                logger.warning("eval: пустое предсказание для %s", img)
                continue
            total += 1
            pl["n"] += 1
            pred_letter = preds[0]["label"]
            ok = pred_letter == letter
            correct += ok
            pl["ok"] += ok
            # угол учитываем ТОЛЬКО при верной букве: на мисклассе период симметрии
            # (по истинной букве) не соответствует декоду (по предсказанной) — мусор
            if ok and true_angle is not None and preds[0].get("angle_valid"):
                err = _angle_error(float(preds[0]["angle_deg"]), true_angle, sym_map.get(letter, "none"))
                ang_errors.append(err)
                pl["ang"].append(err)
            logger.info(
                "  %s/%s -> %s (%.2f)%s",
                letter,
                img.name,
                pred_letter,
                preds[0]["confidence"],
                f"  angle={preds[0].get('angle_deg', float('nan')):.0f}° err={ang_errors[-1]:.1f}°"
                if (true_angle is not None and preds[0].get("angle_valid"))
                else "",
            )

    acc = correct / total if total else 0.0
    errs = np.array(ang_errors)
    summary: dict[str, Any] = {
        "model": model_id,
        "samples": total,
        "accuracy": round(acc, 4),
        "angle_mae_deg": round(float(errs.mean()), 2) if errs.size else None,
        "angle_p95_deg": round(float(np.percentile(errs, 95)), 2) if errs.size else None,
        f"angle_within_{within_deg:g}deg": round(float((errs <= within_deg).mean()), 4) if errs.size else None,
        "per_letter": {
            k: {
                "n": v["n"],
                "acc": round(v["ok"] / v["n"], 3) if v["n"] else 0.0,
                "angle_mae": round(float(np.mean(v["ang"])), 1) if v["ang"] else None,
            }
            for k, v in per_letter.items()
        },
    }
    return summary
