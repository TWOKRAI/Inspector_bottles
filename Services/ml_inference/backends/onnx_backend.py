"""ONNXRuntimeBackend — backend на onnxruntime (основной, кросс-форматный).

Graceful import: модуль импортируется без onnxruntime, но создание backend без
установленного рантайма бросит понятную ошибку (см. ONNX_AVAILABLE).
CPU/CUDA выбирается через execution providers.
"""

from __future__ import annotations

import gc
import logging

import numpy as np

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec

logger = logging.getLogger(__name__)

try:
    import onnxruntime as ort

    ONNX_AVAILABLE = True
except ImportError:  # pragma: no cover — зависит от окружения
    ort = None  # type: ignore[assignment]
    ONNX_AVAILABLE = False


def _providers_for(device: str) -> list[str]:
    """Список execution providers под устройство (с fallback на CPU)."""
    if device == "cuda" and ONNX_AVAILABLE:
        available = ort.get_available_providers()
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        logger.warning("ONNXBackend: CUDA недоступна, fallback на CPU")
    return ["CPUExecutionProvider"]


class ONNXRuntimeBackend(BaseInferenceBackend):
    """Инференс через onnxruntime.InferenceSession.

    InferenceSession НЕ thread-safe при некоторых конфигурациях — вызывать infer()
    последовательно (плагин помечен thread_safe=False).
    """

    def __init__(self) -> None:
        super().__init__()
        if not ONNX_AVAILABLE:
            raise RuntimeError("onnxruntime не установлен. Установите: pip install '.[ml]'")
        self._session: ort.InferenceSession | None = None
        self._input_name: str = ""

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        """Создать InferenceSession из весов .onnx."""
        path = str(spec.weights_path)
        self._session = ort.InferenceSession(path, providers=_providers_for(device))
        self._input_name = self._session.get_inputs()[0].name
        self._spec = spec
        self._device = device
        logger.info(
            "ONNXBackend: загружена %s (%s, providers=%s)",
            spec.name,
            device,
            self._session.get_providers(),
        )

    def infer(self, tensor: np.ndarray) -> np.ndarray:
        """Прогнать тензор → сырой выход первого output."""
        if self._session is None:
            raise RuntimeError("ONNXBackend: модель не загружена")
        outputs = self._session.run(None, {self._input_name: tensor})
        return np.asarray(outputs[0])

    def unload(self) -> None:
        """Освободить сессию."""
        self._session = None
        self._input_name = ""
        self._spec = None
        gc.collect()
