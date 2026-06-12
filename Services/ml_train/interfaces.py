"""Публичные контракты сервиса обучения.

Protocol для structural subtyping: трейнер и экспорт не привязаны к конкретным
классам — любой датасет с контрактом (image, target-dict) и любой источник
прогонов с метриками подходят (подменяемы в тестах).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TrainSample(Protocol):
    """Контракт датасета обучения (структурно совместим с torch Dataset).

    __getitem__ → (image, target):
      image  — тензор CHW float32 (нормализованный);
      target — dict: class_index (long), angle (float32 [sin, cos]),
               angle_valid (bool — маска loss по углу).
    """

    def __len__(self) -> int: ...

    def __getitem__(self, idx: int) -> tuple[Any, dict[str, Any]]: ...


@runtime_checkable
class RunSource(Protocol):
    """Контракт источника прогонов для сравнения/выбора (см. selection.RunRegistry)."""

    def scan(self) -> dict[str, Any]:
        """Пересканировать каталог прогонов."""
        ...

    def best(self, metric: str = "balanced_accuracy") -> Any | None:
        """Лучший прогон по метрике (None — нет кандидатов)."""
        ...


@runtime_checkable
class ModelExporter(Protocol):
    """Контракт экспортёра чекпоинта в формат инференса."""

    def __call__(
        self,
        checkpoint_path: str | Path,
        models_dir: str | Path = ...,
        model_id: str | None = ...,
        opset: int = ...,
        verify: bool = ...,
    ) -> Path: ...
