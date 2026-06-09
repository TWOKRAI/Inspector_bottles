"""ml_inference — сервис инференса нейросетей (вход кадр → классы + confidence).

Архитектура (по образцу Services/modbus):
    core/     — data-driven препроцессинг/постобработка + каталог моделей (без ML-либ)
    backends/ — реализации рантаймов: ONNX Runtime (основной), torch (опц.)
    engine.py — InferenceEngine: каталог + backend + pre/post, кэш модели
    plugin/   — тонкий плагин для pipeline (кадр → engine → predictions)

Универсальность через model registry + sidecar-метаданные (см. data/models/README.md):
новая модель = веса + `<basename>.yaml`, код не трогаем.

Публичный API (eager — работает без onnxruntime/torch):
    InferenceEngine, ModelRegistry, ModelSpec, Normalize, preprocess, classify_postprocess

Plugin-слой — лениво (только при явном импорте):
    from Services.ml_inference import MLInferencePlugin
"""

from Services.ml_inference.backends import ONNX_AVAILABLE, TORCH_AVAILABLE
from Services.ml_inference.core import (
    ModelRegistry,
    ModelSpec,
    Normalize,
    classify_postprocess,
    preprocess,
)
from Services.ml_inference.engine import InferenceEngine

__all__ = [
    "InferenceEngine",
    "ModelRegistry",
    "ModelSpec",
    "Normalize",
    "preprocess",
    "classify_postprocess",
    "ONNX_AVAILABLE",
    "TORCH_AVAILABLE",
]


def __getattr__(name: str):
    """Ленивая загрузка plugin-слоя (тянет multiprocess_framework)."""
    if name == "MLInferencePlugin":
        from Services.ml_inference.plugin.plugin import MLInferencePlugin

        return MLInferencePlugin
    if name == "MLInferenceRegisters":
        from Services.ml_inference.plugin.registers import MLInferenceRegisters

        return MLInferenceRegisters
    if name == "MLInferenceConfig":
        from Services.ml_inference.plugin.config import MLInferenceConfig

        return MLInferenceConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
