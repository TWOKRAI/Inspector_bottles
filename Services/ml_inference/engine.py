"""InferenceEngine — фасад: каталог + backend + препроцессинг + постобработка.

Связывает всё воедино и держит загруженную модель в кэше. Один движок на плагин;
смена модели выгружает предыдущую (освобождение памяти/GPU).

Поток predict():
    BGR-кадр → preprocess(spec) → backend.infer → classify_postprocess → list[dict]
"""

from __future__ import annotations

import logging

import numpy as np

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.backends.onnx_backend import ONNX_AVAILABLE, ONNXRuntimeBackend
from Services.ml_inference.backends.torch_backend import TORCH_AVAILABLE, TorchBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.core.postprocess import classify_postprocess
from Services.ml_inference.core.preprocess import preprocess
from Services.ml_inference.core.registry import ModelRegistry

logger = logging.getLogger(__name__)


def _make_backend(backend_type: str) -> BaseInferenceBackend:
    """Фабрика backend по типу из ModelSpec (понятная ошибка если библиотека не стоит)."""
    if backend_type == "onnx":
        if not ONNX_AVAILABLE:
            raise RuntimeError("backend 'onnx' недоступен: pip install '.[ml]'")
        return ONNXRuntimeBackend()
    if backend_type == "torch":
        if not TORCH_AVAILABLE:
            raise RuntimeError("backend 'torch' недоступен: pip install '.[ml-torch]'")
        return TorchBackend()
    raise ValueError(f"неизвестный backend: {backend_type}")


class InferenceEngine:
    """Высокоуровневый движок инференса для одной модели за раз."""

    def __init__(self, models_dir: str) -> None:
        self._registry = ModelRegistry(models_dir)
        self._registry.scan()
        self._backend: BaseInferenceBackend | None = None
        self._spec: ModelSpec | None = None
        self._labels: list[str] | None = None
        self._device: str = "cpu"

    @property
    def registry(self) -> ModelRegistry:
        """Каталог моделей (для GUI-списка)."""
        return self._registry

    @property
    def current_model(self) -> str | None:
        """Имя текущей загруженной модели или None."""
        return self._spec.name if self._spec else None

    @property
    def is_ready(self) -> bool:
        """Готов ли движок к predict()."""
        return self._backend is not None and self._backend.is_loaded

    def load_model(self, model_id: str, device: str = "cpu") -> None:
        """Загрузить модель по id из каталога (с выгрузкой предыдущей)."""
        spec = self._registry.get(model_id)
        if spec is None:
            # перескан на случай новых файлов
            self._registry.scan()
            spec = self._registry.get(model_id)
        if spec is None:
            raise ValueError(f"модель не найдена в каталоге: {model_id}")

        self.unload()
        backend = _make_backend(spec.backend)
        backend.load(spec, device=device)
        backend.warmup()
        self._backend = backend
        self._spec = spec
        self._labels = spec.load_labels()
        self._device = device
        logger.info("InferenceEngine: модель '%s' готова (%s)", model_id, device)

    def predict(self, frame: np.ndarray, *, top_k: int = 5, threshold: float = 0.0) -> list[dict]:
        """BGR-кадр → топ-K предсказаний. Пустой список если движок не готов."""
        if not self.is_ready or self._spec is None or self._backend is None:
            return []
        tensor = preprocess(frame, self._spec)
        raw = self._backend.infer(tensor)
        return classify_postprocess(raw, labels=self._labels, top_k=top_k, threshold=threshold)

    def unload(self) -> None:
        """Выгрузить текущую модель и освободить ресурсы."""
        if self._backend is not None:
            self._backend.unload()
        self._backend = None
        self._spec = None
        self._labels = None
