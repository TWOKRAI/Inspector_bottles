# -*- coding: utf-8 -*-
"""
domain/protocols/display_catalog.py — Protocol для реестра дисплеев (read+write).

DisplayCatalog — контракт read+write store, который domain ждёт от DisplayRegistry.
Phase C создал адаптер DisplayCatalogFromRegistry; Phase F расширил до writable store.

Sidecar-dataclasses:
  DisplaySpec — описание дисплея (id, имя, конфигурация, метаданные).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class DisplaySpec:
    """Описание дисплея из реестра.

    Первые два поля обязательны, остальные — конфигурационные дефолты.
    metadata оставлен для расширяемости (пользовательские ключи).
    """

    display_id: str
    display_name: str
    width: int = 1280
    height: int = 720
    format: str = "BGR"
    fps_limit: float = 30.0
    ring_buffer_blocks: int = 3
    metadata: dict[str, Any] = field(default_factory=dict)


class DisplayCatalog(Protocol):
    """Контракт read+write store для реестра дисплеев.

    Read-методы (Phase C): list_displays, resolve.
    Write-методы (Phase F): register, unregister, has, persist.

    Реализации: DisplayCatalogFromRegistry (adapter), FakeDisplayCatalog (тесты).
    """

    def list_displays(self) -> tuple[DisplaySpec, ...]:
        """Вернуть все доступные дисплеи."""
        ...

    def resolve(self, display_id: str) -> DisplaySpec | None:
        """Найти дисплей по id. Возвращает None если не найден."""
        ...

    def register(self, spec: DisplaySpec) -> None:
        """Зарегистрировать дисплей. Бросает ValueError при дубликате id."""
        ...

    def unregister(self, display_id: str) -> bool:
        """Удалить дисплей по id. Возвращает True если удалён, False если не найден."""
        ...

    def has(self, display_id: str) -> bool:
        """Проверить наличие дисплея по id."""
        ...

    def persist(self) -> None:
        """Сохранить текущее состояние в YAML (путь знает adapter)."""
        ...


__all__ = [
    "DisplaySpec",
    "DisplayCatalog",
]
