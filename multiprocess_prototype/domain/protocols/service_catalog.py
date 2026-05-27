# -*- coding: utf-8 -*-
"""
domain/protocols/service_catalog.py — Protocol для реестра сервисов (read-only).

ServiceCatalog — минимальный контракт, который domain ждёт от ServiceRegistry.
Phase C создаст адаптер ServiceRegistryAdapter.

Sidecar-dataclasses:
  ServiceSpec — описание сервиса (id, отображаемое имя, метаданные).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """Описание сервиса из реестра."""

    service_id: str
    display_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ServiceCatalog(Protocol):
    """Контракт для read-only доступа к реестру сервисов.

    Реализации: ServiceRegistryAdapter (Phase C), _FakeServiceCatalog (тесты).
    """

    def list_services(self) -> tuple[ServiceSpec, ...]:
        """Вернуть все доступные сервисы."""
        ...

    def resolve(self, service_id: str) -> ServiceSpec | None:
        """Найти сервис по id. Возвращает None если не найден."""
        ...


__all__ = [
    "ServiceSpec",
    "ServiceCatalog",
]
