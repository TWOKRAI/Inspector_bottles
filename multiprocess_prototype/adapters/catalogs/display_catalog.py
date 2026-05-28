# -*- coding: utf-8 -*-
"""
adapters/catalogs/display_catalog.py — адаптер реестра дисплеев.

DisplayCatalogFromRegistry оборачивает DisplayRegistry (singleton из framework)
и реализует domain Protocol DisplayCatalog (read+write store).

Маппинг DisplayEntry <-> DisplaySpec:
    entry.id     → spec.display_id
    entry.name   → spec.display_name
    entry.width/height/format/fps_limit/ring_buffer_blocks → spec first-class поля

Singleton: DisplayRegistry() вызывается напрямую (не через ctx.extras —
audit Phase C зафиксировал: в ctx.extras его нет).

Границы импортов:
    - Разрешено: domain.protocols, multiprocess_framework.modules.display_module
    - ЗАПРЕЩЕНО: PySide6/Qt, multiprocess_prototype.frontend.*
"""

from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.display_module.interfaces import DisplayEntry
from multiprocess_framework.modules.display_module.registry import DisplayRegistry
from multiprocess_prototype.domain.protocols.display_catalog import (
    DisplayCatalog,
    DisplaySpec,
)

# Путь по умолчанию для YAML-персистентности дисплеев.
# Совпадает с preload в app.py и _DEFAULT_YAML_PATH в tab.py.
_DEFAULT_YAML_PATH = Path("multiprocess_prototype/backend/config/displays.yaml")


def _entry_to_spec(entry: DisplayEntry) -> DisplaySpec:
    """Конвертировать DisplayEntry (framework) в DisplaySpec (domain).

    Args:
        entry: Запись дисплея из DisplayRegistry.

    Returns:
        Frozen DisplaySpec с first-class полями конфигурации.
    """
    return DisplaySpec(
        display_id=entry.id,
        display_name=entry.name,
        width=entry.width,
        height=entry.height,
        format=entry.format,
        fps_limit=entry.fps_limit,
        ring_buffer_blocks=entry.ring_buffer_blocks,
    )


def _spec_to_entry(spec: DisplaySpec) -> DisplayEntry:
    """Конвертировать DisplaySpec (domain) в DisplayEntry (framework).

    Args:
        spec: Domain-спецификация дисплея.

    Returns:
        DisplayEntry для регистрации в framework DisplayRegistry.
    """
    return DisplayEntry(
        id=spec.display_id,
        name=spec.display_name,
        width=spec.width,
        height=spec.height,
        format=spec.format,
        fps_limit=spec.fps_limit,
        ring_buffer_blocks=spec.ring_buffer_blocks,
    )


class DisplayCatalogFromRegistry:
    """Adapter: DisplayRegistry → DisplayCatalog Protocol (read+write).

    Реализует domain Protocol DisplayCatalog, делегируя вызовы
    реальному DisplayRegistry (singleton) из multiprocess_framework.

    DisplayRegistry — singleton через __new__, поэтому DisplayRegistry()
    всегда возвращает тот же экземпляр.

    Пример использования:
        catalog = DisplayCatalogFromRegistry(DisplayRegistry())
        displays = catalog.list_displays()
        catalog.register(DisplaySpec(display_id="cam1", display_name="Камера 1"))
        catalog.persist()
    """

    def __init__(
        self,
        registry: DisplayRegistry,
        yaml_path: Path | None = None,
    ) -> None:
        """Инициализировать адаптер.

        Args:
            registry: Экземпляр DisplayRegistry (singleton).
            yaml_path: Путь к YAML для persist(). По умолчанию _DEFAULT_YAML_PATH.
        """
        self._registry = registry
        self._yaml_path = yaml_path if yaml_path is not None else _DEFAULT_YAML_PATH

    # ------------------------------------------------------------------ #
    #  Read (Phase C)                                                      #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    #  Write (Phase F)                                                     #
    # ------------------------------------------------------------------ #

    def register(self, spec: DisplaySpec) -> None:
        """Зарегистрировать дисплей. Бросает ValueError при дубликате id.

        Args:
            spec: Domain-спецификация дисплея для регистрации.

        Raises:
            ValueError: если дисплей с таким id уже существует.
        """
        self._registry.register(_spec_to_entry(spec))

    def unregister(self, display_id: str) -> bool:
        """Удалить дисплей по id.

        Args:
            display_id: Идентификатор дисплея для удаления.

        Returns:
            True если дисплей удалён, False если не найден.
        """
        return self._registry.unregister(display_id)

    def has(self, display_id: str) -> bool:
        """Проверить наличие дисплея по id.

        Args:
            display_id: Идентификатор дисплея.

        Returns:
            True если дисплей зарегистрирован.
        """
        return display_id in self._registry

    def persist(self) -> None:
        """Сохранить текущее состояние реестра в YAML-файл.

        Путь задаётся при инициализации адаптера (по умолчанию _DEFAULT_YAML_PATH).
        """
        self._registry.persist(self._yaml_path)


# Проверка structural subtyping (import-time)
_: DisplayCatalog = DisplayCatalogFromRegistry.__new__(DisplayCatalogFromRegistry)  # type: ignore[assignment]

__all__ = [
    "DisplayCatalogFromRegistry",
]
