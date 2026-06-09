"""core — data-driven препроцессинг, постобработка и каталог моделей.

Этот слой НЕ зависит от ML-библиотек (onnxruntime/torch) — только numpy + opencv.
Импортируется всегда, даже если backend-библиотека не установлена.
"""

from Services.ml_inference.core.model_spec import (
    BackendType,
    ColorOrder,
    LayoutType,
    ModelSpec,
    Normalize,
    TaskType,
)
from Services.ml_inference.core.postprocess import classify_postprocess, softmax
from Services.ml_inference.core.preprocess import letterbox, preprocess
from Services.ml_inference.core.registry import ModelRegistry

__all__ = [
    "ModelSpec",
    "Normalize",
    "TaskType",
    "BackendType",
    "LayoutType",
    "ColorOrder",
    "ModelRegistry",
    "preprocess",
    "letterbox",
    "classify_postprocess",
    "softmax",
]
