# -*- coding: utf-8 -*-
"""
adapters/catalogs/service_catalog.py — адаптер реестра сервисов.

ServiceCatalogFromRegistry оборачивает ServiceRegistry (из framework)
и реализует domain Protocol ServiceCatalog.

Маппинг ServiceEntry → ServiceSpec:
    entry.name          → spec.service_id
    entry.cls.__name__  → spec.display_name (человекочитаемое имя)
    entry.meta          → spec.metadata

Границы импортов:
    - Разрешено: domain.protocols, multiprocess_framework.modules.service_module
    - ЗАПРЕЩЕНО: PySide6/Qt, multiprocess_prototype.frontend.*
"""

from __future__ import annotations

from multiprocess_framework.modules.service_module.registry import (
    ServiceEntry,
    ServiceRegistry,
)
from multiprocess_prototype.domain.protocols.service_catalog import (
    ServiceCatalog,
    ServiceSpec,
)


def _entry_to_spec(entry: ServiceEntry) -> ServiceSpec:
    """Конвертировать ServiceEntry в ServiceSpec.

    Args:
        entry: Запись сервиса из ServiceRegistry.

    Returns:
        Frozen ServiceSpec для domain-слоя.
    """
    return ServiceSpec(
        service_id=entry.name,
        display_name=entry.cls.__name__,
        metadata=dict(entry.meta),
    )


class ServiceCatalogFromRegistry:
    """Adapter: ServiceRegistry → ServiceCatalog Protocol.

    Реализует domain Protocol ServiceCatalog, делегируя вызовы
    реальному ServiceRegistry (singleton) из multiprocess_framework.

    Пример использования:
        from multiprocess_framework.modules.service_module.registry import ServiceRegistry
        catalog = ServiceCatalogFromRegistry(ServiceRegistry())
        services = catalog.list_services()
    """

    def __init__(self, registry: ServiceRegistry) -> None:
        """Инициализировать адаптер.

        Args:
            registry: Экземпляр ServiceRegistry (singleton).
        """
        self._registry = registry

    def list_services(self) -> tuple[ServiceSpec, ...]:
        """Вернуть все доступные сервисы как ServiceSpec.

        Returns:
            Tuple ServiceSpec для всех зарегистрированных сервисов.
        """
        return tuple(_entry_to_spec(entry) for entry in self._registry.list())

    def resolve(self, service_id: str) -> ServiceSpec | None:
        """Найти сервис по идентификатору.

        Args:
            service_id: Уникальное имя сервиса.

        Returns:
            ServiceSpec если сервис найден, иначе None.
        """
        entry = self._registry.get(service_id)
        if entry is None:
            return None
        return _entry_to_spec(entry)


# Проверка structural subtyping (import-time)
_: ServiceCatalog = ServiceCatalogFromRegistry.__new__(ServiceCatalogFromRegistry)  # type: ignore[assignment]

__all__ = [
    "ServiceCatalogFromRegistry",
]
