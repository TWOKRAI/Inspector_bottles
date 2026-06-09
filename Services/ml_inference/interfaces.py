"""Публичные контракты сервиса инференса.

Protocol вместо ABC для внешних потребителей — structural subtyping. BaseInferenceBackend
(ABC в backends/base.py) — для реализаций внутри сервиса.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from Services.ml_inference.core.model_spec import ModelSpec


@runtime_checkable
class InferenceBackend(Protocol):
    """Контракт backend-рантайма (ONNX, torch, ...)."""

    @property
    def is_loaded(self) -> bool:
        """Загружена ли модель."""
        ...

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        """Загрузить модель из spec на устройство (cpu|cuda)."""
        ...

    def warmup(self) -> None:
        """Прогреть модель фиктивным прогоном (убрать спайк первого кадра)."""
        ...

    def infer(self, tensor: np.ndarray) -> np.ndarray:
        """Прогнать предобработанный тензор → сырой выход сети."""
        ...

    def unload(self) -> None:
        """Освободить ресурсы (память/GPU)."""
        ...


@runtime_checkable
class ModelCatalog(Protocol):
    """Контракт каталога моделей (для GUI и движка)."""

    def scan(self) -> dict[str, ModelSpec]:
        """Пересканировать источник моделей."""
        ...

    def names(self) -> list[str]:
        """Список идентификаторов моделей."""
        ...

    def get(self, model_id: str) -> ModelSpec | None:
        """ModelSpec по id или None."""
        ...
