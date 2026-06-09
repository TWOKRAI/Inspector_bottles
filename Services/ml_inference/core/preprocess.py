"""Препроцессинг кадра под вход сети — полностью data-driven по ModelSpec.

Вход: BGR-кадр (H, W, 3) uint8 (формат pipeline проекта, OpenCV-native).
Выход: float32-тензор готовый к backend.infer() с layout/нормализацией из spec.

Шаги (по ModelSpec):
    1. resize → input_size (letterbox с сохранением пропорций или stretch);
    2. порядок каналов BGR → spec.color (RGB/BGR);
    3. нормализация: pixel/255 → (x - mean) / std;
    4. layout: HWC → NCHW или NHWC, добавление batch-измерения.
"""

from __future__ import annotations

import cv2
import numpy as np

from Services.ml_inference.core.model_spec import ModelSpec


def letterbox(frame: np.ndarray, size: tuple[int, int], pad_value: int = 114) -> np.ndarray:
    """Resize с сохранением пропорций + паддинг до (H, W).

    Серый паддинг 114 — конвенция YOLO/Ultralytics; для классификации
    сохраняет геометрию объекта без искажений.
    """
    target_h, target_w = size
    h, w = frame.shape[:2]
    scale = min(target_h / h, target_w / w)
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    canvas = np.full((target_h, target_w, frame.shape[2]), pad_value, dtype=frame.dtype)
    top = (target_h - new_h) // 2
    left = (target_w - new_w) // 2
    canvas[top : top + new_h, left : left + new_w] = resized
    return canvas


def preprocess(frame: np.ndarray, spec: ModelSpec, *, keep_aspect: bool = True) -> np.ndarray:
    """BGR-кадр → нормализованный float32-тензор по ModelSpec.

    Args:
        frame: BGR uint8 (H, W, 3).
        spec: метаданные модели (input_size, color, normalize, layout).
        keep_aspect: True — letterbox (сохранить пропорции), False — stretch.

    Returns:
        np.float32 батч-тензор формы (1, C, H, W) для NCHW или (1, H, W, C) для NHWC.
    """
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"ожидается BGR-кадр (H, W, 3), получено {frame.shape}")

    target_h, target_w = spec.input_size

    if keep_aspect:
        img = letterbox(frame, (target_h, target_w))
    else:
        img = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

    # Порядок каналов: pipeline отдаёт BGR; сеть может ждать RGB.
    if spec.color == "RGB":
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # Нормализация в float32.
    img = img.astype(np.float32) / 255.0
    mean = np.array(spec.normalize.mean, dtype=np.float32)
    std = np.array(spec.normalize.std, dtype=np.float32)
    img = (img - mean) / std

    # Layout + batch.
    if spec.layout == "NCHW":
        img = np.transpose(img, (2, 0, 1))  # HWC → CHW
    tensor = np.expand_dims(img, axis=0)  # → (1, ...)
    return np.ascontiguousarray(tensor, dtype=np.float32)
