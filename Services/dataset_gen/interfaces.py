"""Публичные контракты сервиса генерации датасета.

Protocol для structural subtyping: export/preview/torch-адаптер принимают
любой SampleGenerator, не только DatasetEngine — движок подменяем
(например, заглушкой в тестах обучающего сервиса).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from Services.dataset_gen.core.config import SymmetryType
from Services.dataset_gen.core.labels import SampleLabel


@runtime_checkable
class SampleGenerator(Protocol):
    """Контракт источника сэмплов «кадр + метка»."""

    @property
    def num_classes(self) -> int:
        """Число классов в каталоге."""
        ...

    @property
    def class_names(self) -> list[str]:
        """Имена классов (индекс в списке == class_index метки)."""
        ...

    @property
    def symmetry_map(self) -> dict[str, SymmetryType]:
        """Имя класса → тип симметрии."""
        ...

    def generate_sample(
        self,
        class_index: int | None = None,
        rng: np.random.Generator | None = None,
    ) -> tuple[np.ndarray, SampleLabel]:
        """Сгенерировать кадр (HxWx3 uint8 RGB) и метку."""
        ...
