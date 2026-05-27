# -*- coding: utf-8 -*-
"""
domain/protocols/display_catalog.py — Protocol для реестра дисплеев (read-only).

DisplayCatalog — минимальный контракт, который domain ждёт от DisplayRegistry.
Phase C создаст адаптер DisplayRegistryAdapter.

Sidecar-dataclasses:
  DisplaySpec — описание дисплея (id, отображаемое имя, метаданные).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DisplaySpec:
    """Описание дисплея из реестра."""

    display_id: str
    display_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


class DisplayCatalog(Protocol):
    """Контракт для read-only доступа к реестру дисплеев.

    Реализации: DisplayRegistryAdapter (Phase C), _FakeDisplayCatalog (тесты).
    """

    def list_displays(self) -> tuple[DisplaySpec, ...]:
        """Вернуть все доступные дисплеи."""
        ...

    def resolve(self, display_id: str) -> DisplaySpec | None:
        """Найти дисплей по id. Возвращает None если не найден."""
        ...


__all__ = [
    "DisplaySpec",
    "DisplayCatalog",
]
