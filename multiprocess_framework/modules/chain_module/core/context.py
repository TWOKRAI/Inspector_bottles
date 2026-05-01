"""Контекст выполнения цепочки обработки.

Передаётся через все шаги цепочки: содержит идентификаторы источника,
счётчики ошибок и предупреждений, список зависших нод.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ChainContext:
    """Контекст, передаваемый между операциями в цепочке обработки."""

    camera_id: str = ""
    region_id: str = ""
    seq_id: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timeouts: list[str] = field(default_factory=list)  # node_id зависших нод
    logger: Any = None  # ObservableMixin-совместимый объект с методами _log_*


@runtime_checkable
class IChainContext(Protocol):
    """Минимальный контракт контекста цепочки (для утиной типизации)."""

    camera_id: str
    region_id: str
    seq_id: int
    warnings: list
    errors: list
    timeouts: list


__all__ = ["ChainContext", "IChainContext"]
