# -*- coding: utf-8 -*-
"""
adapters/catalogs/display_catalog.py — адаптер реестра дисплеев.

DisplayCatalogFromRegistry оборачивает DisplayRegistry (singleton из framework)
и реализует domain Protocol DisplayCatalog.

Маппинг DisplayEntry → DisplaySpec:
    entry.id     → spec.display_id
    entry.name   → spec.display_name
    остальные поля (width, height, format, fps_limit, ring_buffer_blocks)
                 → spec.metadata

Singleton: DisplayRegistry() вызывается напрямую (не через ctx.extras —
audit Phase C зафиксировал: в ctx.extras его нет).

Границы импортов:
    - Разрешено: domain.protocols, multiprocess_framework.modules.display_module
    - ЗАПРЕЩЕНО: PySide6/Qt, multiprocess_prototype.frontend.*
"""

from __future__ import annotations

from multiprocess_framework.modules.display_module.interfaces import DisplayEntry
from multiprocess_framework.modules.display_module.registry import DisplayRegistry
from multiprocess_prototype.domain.protocols.display_catalog import (
    DisplayCatalog,
    DisplaySpec,
)


def _entry_to_spec(entry: DisplayEntry) -> DisplaySpec:
    """Конвертировать DisplayEntry в DisplaySpec.

    Args:
        entry: Запись дисплея из DisplayRegistry.

    Returns:
        Frozen DisplaySpec для domain-слоя.
    """
    return DisplaySpec(
        display_id=entry.id,
        display_name=entry.name,
        metadata={
            "width": entry.width,
            "height": entry.height,
            "format": entry.format,
            "fps_limit": entry.fps_limit,
            "ring_buffer_blocks": entry.ring_buffer_blocks,
        },
    )


class DisplayCatalogFromRegistry:
    """Adapter: DisplayRegistry → DisplayCatalog Protocol.

    Реализует domain Protocol DisplayCatalog, делегируя вызовы
    реальному DisplayRegistry (singleton) из multiprocess_framework.

    DisplayRegistry — singleton через __new__, поэтому DisplayRegistry()
    всегда возвращает тот же экземпляр.

    Пример использования:
        catalog = DisplayCatalogFromRegistry(DisplayRegistry())
        displays = catalog.list_displays()
    """

    def __init__(self, registry: DisplayRegistry) -> None:
        """Инициализировать адаптер.

        Args:
            registry: Экземпляр DisplayRegistry (singleton).
        """
        self._registry = registry

    def list_displays(self) -> tuple[DisplaySpec, ...]:
        """Вернуть все доступные дисплеи как DisplaySpec.

        Returns:
            Tuple DisplaySpec для всех зарегистрированных дисплеев.
        """
        return tuple(_entry_to_spec(entry) for entry in self._registry.list())

    def resolve(self, display_id: str) -> DisplaySpec | None:
        """Найти дисплей по идентификатору.

        Args:
            display_id: Уникальный идентификатор дисплея.

        Returns:
            DisplaySpec если дисплей найден, иначе None.
        """
        entry = self._registry.get(display_id)
        if entry is None:
            return None
        return _entry_to_spec(entry)


# Проверка structural subtyping (import-time)
_: DisplayCatalog = DisplayCatalogFromRegistry.__new__(DisplayCatalogFromRegistry)  # type: ignore[assignment]

__all__ = [
    "DisplayCatalogFromRegistry",
]
