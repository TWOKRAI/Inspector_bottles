# -*- coding: utf-8 -*-
"""
domain/protocols/service_catalog.py — Protocol для управления сервисами.

ServiceManager — расширенный контракт (lifecycle + read) для ServiceRegistry.
Phase C.1.6: расширение read-only ServiceCatalog до ServiceManager с lifecycle.

ServiceCatalog — backward-compatible alias для ServiceManager (Phase B legacy).

Sidecar-dataclasses:
  ServiceSpec — описание сервиса (id, отображаемое имя, метаданные).

Реэкспорт:
  ServiceLifecycle — enum из multiprocess_framework (не дублирован).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from multiprocess_framework.modules.service_module.interfaces import ServiceLifecycle


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """Описание сервиса из реестра."""

    service_id: str
    display_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ServiceManager(Protocol):
    """Контракт для управления реестром сервисов (read + lifecycle).

    Read-only методы (list_services, resolve) — совместимы с Phase B ServiceCatalog.
    Lifecycle методы (start, stop, restart, get_lifecycle) — Phase C.1.6 расширение.

    Реализации:
        ServiceManagerFromRegistry (adapters/catalogs) — prod.
        FakeServiceManager (domain/tests/_fakes.py) — тесты.

    Idempotency:
        start() на уже RUNNING сервисе — no-op.
        stop() на уже STOPPED сервисе — no-op.
    """

    def list_services(self) -> tuple[ServiceSpec, ...]:
        """Вернуть все доступные сервисы."""
        ...

    def resolve(self, service_id: str) -> ServiceSpec | None:
        """Найти сервис по id. Возвращает None если не найден."""
        ...

    def start(self, service_id: str) -> None:
        """Инстанцирует и запускает сервис. Idempotent: если уже RUNNING — no-op.

        Raises:
            DomainError: если service_id неизвестен или инстанцирование/старт провалились.
        """
        ...

    def stop(self, service_id: str) -> None:
        """Останавливает сервис. Idempotent: если уже STOPPED — no-op.

        Raises:
            DomainError: если service_id неизвестен или остановка провалилась.
        """
        ...

    def restart(self, service_id: str) -> None:
        """stop() + start().

        Raises:
            DomainError: если service_id неизвестен или stop/start провалились.
        """
        ...

    def get_lifecycle(self, service_id: str) -> ServiceLifecycle:
        """Текущий lifecycle статус сервиса.

        Raises:
            DomainError: если service_id неизвестен.
        """
        ...


# Backward-compatible alias (Phase B legacy).
# Все старые импорты `from ...service_catalog import ServiceCatalog` продолжают работать.
ServiceCatalog = ServiceManager

__all__ = [
    "ServiceSpec",
    "ServiceManager",
    "ServiceCatalog",
    "ServiceLifecycle",
]
