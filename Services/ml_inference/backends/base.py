"""BaseInferenceBackend — общий ABC для всех backend-рантаймов.

Реализации (onnx, torch) скрывают конкретный рантайм за единым интерфейсом, чтобы
плагин и движок не зависели от формата весов. Добавить TensorRT/OpenVINO позже =
новый подкласс, без правок выше по стеку.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from Services.ml_inference.core.model_spec import ModelSpec


class BaseInferenceBackend(ABC):
    """Контракт backend-рантайма инференса."""

    def __init__(self) -> None:
        self._spec: ModelSpec | None = None
        self._device: str = "cpu"

    @property
    def is_loaded(self) -> bool:
        """Загружена ли модель."""
        return self._spec is not None

    @property
    def spec(self) -> ModelSpec | None:
        """ModelSpec текущей загруженной модели."""
        return self._spec

    @abstractmethod
    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        """Загрузить модель из spec на устройство (cpu|cuda)."""

    @abstractmethod
    def infer(self, tensor: np.ndarray) -> np.ndarray:
        """Прогнать предобработанный тензор → сырой выход сети."""

    @abstractmethod
    def unload(self) -> None:
        """Освободить ресурсы (память/GPU)."""

    def warmup(self) -> None:
        """Прогреть модель фиктивным прогоном по форме входа из spec.

        Базовая реализация генерирует нулевой тензор нужной формы и прогоняет infer().
        """
        if self._spec is None:
            return
        h, w = self._spec.input_size
        c = 3
        shape = (1, c, h, w) if self._spec.layout == "NCHW" else (1, h, w, c)
        dummy = np.zeros(shape, dtype=np.float32)
        self.infer(dummy)
