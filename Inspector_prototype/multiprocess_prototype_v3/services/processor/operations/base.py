"""Базовые интерфейсы цепочки обработки кадров."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass
class ChainContext:
    """Контекст, передаваемый между операциями в цепочке обработки."""

    camera_id: str = ""
    region_id: str = ""
    seq_id: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timeouts: list[str] = field(default_factory=list)  # node_id зависших нод


@runtime_checkable
class ProcessingOperation(Protocol):
    """Протокол операции обработки кадра.

    Каждая операция получает кадр + контекст, возвращает обработанный кадр.
    Побочные эффекты (детекции, предупреждения) пишутся в context.
    """

    def execute(self, frame: np.ndarray, context: ChainContext) -> np.ndarray:
        """Обработать кадр, вернуть результат."""
        ...

    def configure(self, params: dict) -> None:
        """Настроить параметры операции."""
        ...
