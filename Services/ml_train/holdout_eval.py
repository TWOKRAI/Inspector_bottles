"""Валидация модели на РЕАЛЬНОМ hold-out — честная приёмка перед выставкой.

Зачем: train/val синтетика из тех же 4 спрайтов меряет переобучение на
синтетику, а не реальный домен. Этот модуль гоняет ЭКСПОРТИРОВАННУЮ модель
через продакшн-путь Services.ml_inference на реальных фото со сцены и считает
то, что важно роботу: точность буквы + ФИЗИЧЕСКУЮ угловую ошибку + долю ≤5°.

Раскладка hold-out (как у real_photos, но это ДРУГИЕ кадры — не из обучения):
    <holdout>/<буква>/<угол>.jpg   (угол = поворот буквы CCW, 0..359)

Путь кадра = как в конвейере перед ml_inference: детекция диска (HoughCircles) →
квадратный вырез по формуле конвейера (`side_from_radius` + `square_crop` с заливкой
`pad_color_bgr` + `resize_square`, те же функции, что у `center_crop`) → engine.predict
(движок делает свой resize по sidecar; при 128→128 он ничего не меняет). Число точности
меряет то, что видит робот. Параметры выреза (`radius_scale`, `margin_px`, `output_size`,
`pad_color_bgr`) — аргументы `evaluate_holdout`, их значения попадают в `summary["crop"]`.
Детектор диска здесь свой (`detect_disk`), в конвейере радиус даёт `circle_detector`.

Запуск:
    python -m Services.ml_train eval <model_id> <holdout_dir> [--models-dir data/models]
"""

from __future__ import annotations


from multiprocess_framework.modules.logger_module import get_std_logger
import re
from pathlib import Path
from typing import Any

import numpy as np

from Services.dataset_gen.core.catalog import imread_unicode
from Services.dataset_gen.core.realcut import detect_disk
from Services.layer_render import resize_square, side_from_radius, square_crop
from Services.ml_inference.engine import InferenceEngine

logger = get_std_logger(__name__)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


def _angle_from_name(stem: str) -> float | None:
    nums = re.findall(r"\d+", stem)
    return float(nums[-1]) % 360.0 if nums else None


def _crop_disk(
    bgr: np.ndarray,
    radius_scale: float,
    margin_px: int,
    output_size: int,
    pad_color_bgr: tuple[int, int, int],
) -> np.ndarray:
    """КВАДРАТНЫЙ вырез вокруг диска по формуле конвейера (как `CenterCropPlugin`).

    Сторона = `side_from_radius(r, radius_scale, margin_px)` = 2·r·radius_scale + 2·margin_px.
    Квадрат обязателен: при resize_policy=stretch прямоугольный вырез растянул бы диск
    и сдвинул угол. У края кадра недостающие поля заливаются `pad_color_bgr` (`oob="pad"`);
    квадрат без пересечения с кадром даёт чистый холст этого цвета, исключения нет.
    Затем `resize_square(crop, output_size)`; `output_size <= 0` — без ресайза.
    Параметры без дефолтов: значения по умолчанию живут только в `evaluate_holdout`.
    Результат — всегда копия кадра, не view.
    """
    cx, cy, r = detect_disk(bgr)
    side = side_from_radius(r, radius_scale, margin_px)
    crop = square_crop(bgr, cx, cy, side, oob="pad", pad_value=pad_color_bgr)
    return resize_square(crop, output_size)


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
    radius_scale: float = 1.0,
    margin_px: int = 14,
    output_size: int = 128,
    pad_color_bgr: tuple[int, int, int] = (0, 0, 0),
    within_deg: float = 5.0,
) -> dict[str, Any]:
    """Прогнать модель по hold-out, вернуть сводку (и залогировать таблицу).

    Параметры выреза по умолчанию = рецепт `letter_robot_sim.yaml` (`center_crop`:
    size_mode radius, radius_scale 1.0, margin_px 14, output_size 128) и дефолт регистра
    `pad_color_bgr = (0, 0, 0)`. Они же возвращаются в `summary["crop"]`.
    """
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
            preds = engine.predict(_crop_disk(bgr, radius_scale, margin_px, output_size, pad_color_bgr), top_k=1)
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
            angle_scored = ok and true_angle is not None and bool(preds[0].get("angle_valid"))
            if angle_scored:
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
                if angle_scored
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
        "crop": {
            "radius_scale": radius_scale,
            "margin_px": margin_px,
            "output_size": output_size,
            "pad_color_bgr": list(pad_color_bgr),
        },
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
