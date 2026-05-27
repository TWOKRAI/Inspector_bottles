# -*- coding: utf-8 -*-
"""
adapters/catalogs/plugin_catalog.py — адаптер реестра плагинов.

PluginCatalogFromRegistry оборачивает _PluginRegistry (из framework)
и реализует domain Protocol PluginCatalog.

Маппинг PluginEntry → PluginSpec:
    entry.name          → spec.name
    entry.category      → spec.category
    entry.inputs        → spec.ports (PortSpec с dtype=port.dtype, name=port.name)
    entry.outputs       → spec.ports (добавляются к inputs)
    entry.register_classes → spec.config_schema (TODO Phase E — пока dict с именами классов)

Границы импортов:
    - Разрешено: domain.protocols, multiprocess_framework.modules.process_module.plugins.registry
    - ЗАПРЕЩЕНО: PySide6/Qt, multiprocess_prototype.frontend.*
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.plugins.registry import (
    PluginEntry,
    _PluginRegistry,
)
from multiprocess_prototype.domain.protocols.plugin_catalog import (
    PluginCatalog,
    PluginSpec,
    PortSpec,
)


def _entry_to_spec(entry: PluginEntry) -> PluginSpec:
    """Конвертировать PluginEntry в PluginSpec.

    Args:
        entry: Запись плагина из _PluginRegistry.

    Returns:
        Frozen PluginSpec для domain-слоя.
    """
    # Входные порты
    input_ports = tuple(PortSpec(name=port.name, dtype=port.dtype) for port in entry.inputs)
    # Выходные порты — добавляем к входным в общий tuple
    output_ports = tuple(PortSpec(name=port.name, dtype=port.dtype) for port in entry.outputs)
    ports = input_ports + output_ports

    # config_schema — Phase E детализирует структуру; сейчас храним имена классов
    config_schema: dict = {
        "register_classes": tuple(
            cls.__name__ if hasattr(cls, "__name__") else str(cls) for cls in entry.register_classes
        )
    }

    return PluginSpec(
        name=entry.name,
        category=entry.category,
        config_schema=config_schema,
        ports=ports,
    )


class PluginCatalogFromRegistry:
    """Adapter: _PluginRegistry → PluginCatalog Protocol.

    Реализует domain Protocol PluginCatalog, делегируя вызовы
    реальному _PluginRegistry из multiprocess_framework.

    Пример использования:
        from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
        catalog = PluginCatalogFromRegistry(PluginRegistry)
        plugins = catalog.list_plugins()
    """

    def __init__(self, registry: _PluginRegistry) -> None:
        """Инициализировать адаптер.

        Args:
            registry: Экземпляр _PluginRegistry (обычно глобальный PluginRegistry).
        """
        self._registry = registry

    def list_plugins(self) -> tuple[PluginSpec, ...]:
        """Вернуть все доступные плагины как PluginSpec.

        Returns:
            Tuple PluginSpec для всех зарегистрированных плагинов.
        """
        return tuple(_entry_to_spec(entry) for entry in self._registry.list())

    def resolve(self, plugin_name: str) -> PluginSpec | None:
        """Найти плагин по имени.

        Args:
            plugin_name: Уникальное имя плагина.

        Returns:
            PluginSpec если плагин найден, иначе None.
        """
        entry = self._registry.get(plugin_name)
        if entry is None:
            return None
        return _entry_to_spec(entry)

    def categories(self) -> tuple[str, ...]:
        """Вернуть уникальные категории всех плагинов (отсортированные).

        Returns:
            Tuple уникальных категорий, отсортированный по алфавиту.
        """
        cats = sorted({entry.category for entry in self._registry.list()})
        return tuple(cats)


# Проверка structural subtyping (import-time, не runtime-checkable)
_: PluginCatalog = PluginCatalogFromRegistry.__new__(PluginCatalogFromRegistry)  # type: ignore[assignment]

__all__ = [
    "PluginCatalogFromRegistry",
]
