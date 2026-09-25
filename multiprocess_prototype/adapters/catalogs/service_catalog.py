# -*- coding: utf-8 -*-
"""
adapters/catalogs/service_catalog.py — адаптер управления сервисами.

ServiceManagerFromRegistry оборачивает ServiceRegistry (из framework)
и реализует domain Protocol ServiceManager (read + lifecycle).

Phase C.1.6: ServiceManagerFromRegistry с lifecycle методами (start/stop/restart/get_lifecycle).

Task 1b.5: lifecycle-логика — в framework ``ServiceHost`` (service_module/host.py),
адаптер — тонкая обёртка над внутрипроцессным хостом (одна копия логики с хабом):
  - Экземпляры кэшируются в хосте (``self._instances`` — делегат).
  - start() инстанцирует cls() и вызывает instance.start({}); ждёт до конца.
  - lifecycle мутируется на entry (ServiceEntry.lifecycle).
  - Плоские ошибки хоста → DomainError (entry.lifecycle = ERROR ставит хост).

Маппинг ServiceEntry → ServiceSpec:
    entry.name          → spec.service_id
    entry.cls.__name__  → spec.display_name (человекочитаемое имя)
    entry.meta          → spec.metadata

Границы импортов:
    - Разрешено: domain.protocols, domain.errors, multiprocess_framework.modules.service_module
    - ЗАПРЕЩЕНО: PySide6/Qt, multiprocess_prototype.frontend.*
"""

from __future__ import annotations


from multiprocess_framework.modules.logger_module import get_std_logger
from typing import Any

from multiprocess_framework.modules.service_module.host import ServiceHost
from multiprocess_framework.modules.service_module.interfaces import ServiceLifecycle
from multiprocess_framework.modules.service_module.registry import (
    ServiceEntry,
    ServiceRegistry,
)
from multiprocess_prototype.domain.errors import DomainError
from multiprocess_prototype.domain.protocols.service_catalog import (
    ServiceManager,
    ServiceSpec,
)

logger = get_std_logger(__name__)


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


class ServiceManagerFromRegistry:
    """Adapter: ServiceRegistry → ServiceManager Protocol.

    Реализует domain Protocol ServiceManager, делегируя вызовы
    реальному ServiceRegistry (singleton) из multiprocess_framework.

    Read-only методы (list_services, resolve) — совместимы с Phase B.
    Lifecycle методы (start, stop, restart, get_lifecycle) — Phase C.1.6.

    Instances кэшируются в self._instances (аналогично ServicesPresenter).
    Lifecycle мутируется на ServiceEntry (entry.lifecycle = ...) — это
    соответствует существующему prod-коду в ServicesPresenter.

    Пример использования:
        from multiprocess_framework.modules.service_module.registry import ServiceRegistry
        manager = ServiceManagerFromRegistry(ServiceRegistry())
        manager.start("webcam_camera")

    Migration note (Phase E):
        Adapter бросает DomainError при сбоях start/stop. Legacy ServicesPresenter
        возвращает bool. При миграции presenter'а в Phase E — оборачивать
        services.start(id) / services.stop(id) в try/except DomainError и
        конвертировать в bool/UI feedback, иначе exception пробросится в Qt
        event loop.
    """

    def __init__(self, registry: ServiceRegistry) -> None:
        """Инициализировать адаптер.

        Args:
            registry: Экземпляр ServiceRegistry (singleton).
        """
        self._registry = registry
        # Task 1b.5: lifecycle живёт в ServiceHost (одна копия логики); ждём старт до конца.
        self._host = ServiceHost(registry, start_wait_sec=None)
        self._handlers = self._host.handlers()

    @property
    def _instances(self) -> dict[str, Any]:
        """Кэш экземпляров хоста (back-compat: тесты кладут instance напрямую)."""
        return self._host._instances

    def _call(self, command: str, service_id: str) -> dict:
        reply = self._handlers[command]({"name": service_id})
        if reply.get("success"):
            return reply
        if reply.get("error") == "unknown_service":
            raise DomainError(f"Unknown service: {service_id}")
        raise DomainError(reply.get("message") or f"{command}({service_id}): {reply.get('error')}")

    # ------------------------------------------------------------------
    # Read-only методы (Phase B / C.1)
    # ------------------------------------------------------------------

    def list_services(self) -> tuple[ServiceSpec, ...]:
        """Вернуть все доступные сервисы как ServiceSpec."""
        return tuple(_entry_to_spec(entry) for entry in self._registry.list())

    def resolve(self, service_id: str) -> ServiceSpec | None:
        """Найти сервис по идентификатору; None если не найден."""
        entry = self._registry.get(service_id)
        if entry is None:
            return None
        return _entry_to_spec(entry)

    # ------------------------------------------------------------------
    # Lifecycle методы (Phase C.1.6) — делегированы ServiceHost
    # ------------------------------------------------------------------

    def start(self, service_id: str) -> None:
        """Инстанцирует и запускает сервис. Idempotent: уже RUNNING — no-op.

        Raises:
            DomainError: неизвестный service_id, сбой cls()/start() или start() вернул False.
        """
        self._call("service.start", service_id)

    def stop(self, service_id: str) -> None:
        """Останавливает сервис. Idempotent: уже STOPPED — no-op; нет instance — lifecycle → STOPPED.

        Raises:
            DomainError: неизвестный service_id, сбой stop() или stop() вернул False.
        """
        self._call("service.stop", service_id)

    def restart(self, service_id: str) -> None:
        """stop() + start(). Raises DomainError как они."""
        self._call("service.restart", service_id)

    def get_lifecycle(self, service_id: str) -> ServiceLifecycle:
        """Текущий lifecycle статус сервиса. Raises DomainError для неизвестного id."""
        entry = self._registry.get(service_id)
        if entry is None:
            raise DomainError(f"Unknown service: {service_id}")
        return entry.lifecycle


# Проверка structural subtyping (import-time)
_: ServiceManager = ServiceManagerFromRegistry.__new__(ServiceManagerFromRegistry)  # type: ignore[assignment]

__all__ = [
    "ServiceManagerFromRegistry",
]
