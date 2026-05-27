# -*- coding: utf-8 -*-
"""
adapters/catalogs/service_catalog.py — адаптер управления сервисами.

ServiceManagerFromRegistry оборачивает ServiceRegistry (из framework)
и реализует domain Protocol ServiceManager (read + lifecycle).

Phase C.1.6: расширение read-only ServiceCatalogFromRegistry до
ServiceManagerFromRegistry с lifecycle методами (start/stop/restart/get_lifecycle).

Lifecycle-логика повторяет паттерн ServicesPresenter
(multiprocess_prototype/frontend/widgets/tabs/services/presenter.py):
  - Экземпляры кэшируются в self._instances.
  - start() инстанцирует cls() и вызывает instance.start({}).
  - stop() вызывает instance.stop().
  - lifecycle мутируется на entry (ServiceEntry.lifecycle).
  - Ошибки инстанцирования/старта/стопа → DomainError + entry.lifecycle = ERROR.

Маппинг ServiceEntry → ServiceSpec:
    entry.name          → spec.service_id
    entry.cls.__name__  → spec.display_name (человекочитаемое имя)
    entry.meta          → spec.metadata

Границы импортов:
    - Разрешено: domain.protocols, domain.errors, multiprocess_framework.modules.service_module
    - ЗАПРЕЩЕНО: PySide6/Qt, multiprocess_prototype.frontend.*
"""

from __future__ import annotations

import logging
from typing import Any

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

logger = logging.getLogger(__name__)


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
        # Кэш запущенных экземпляров: name → instance.
        self._instances: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Read-only методы (Phase B / C.1)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Lifecycle методы (Phase C.1.6)
    # ------------------------------------------------------------------

    def start(self, service_id: str) -> None:
        """Инстанцирует и запускает сервис. Idempotent: если уже RUNNING — no-op.

        Паттерн повторяет ServicesPresenter.start_service():
        1. Получить entry из registry.
        2. Если instance не в кэше — cls() для создания.
        3. instance.start({}) — запуск.
        4. entry.lifecycle = RUNNING (или ERROR при ошибке).

        Args:
            service_id: Уникальное имя сервиса.

        Raises:
            DomainError: если service_id неизвестен.
            DomainError: если инстанцирование или start() провалились.
        """
        entry = self._registry.get(service_id)
        if entry is None:
            raise DomainError(f"Unknown service: {service_id}")

        # Idempotent: уже RUNNING — no-op
        if entry.lifecycle == ServiceLifecycle.RUNNING:
            logger.debug("ServiceManagerFromRegistry: start(%s) — already RUNNING, no-op", service_id)
            return

        # Инстанцируем если ещё нет в кэше
        instance = self._instances.get(service_id)
        if instance is None:
            try:
                instance = entry.cls()
            except Exception as exc:
                entry.lifecycle = ServiceLifecycle.ERROR
                raise DomainError(f"Failed to instantiate service '{service_id}': {exc}") from exc
            self._instances[service_id] = instance

        # Запуск: вызываем instance.start({}) как в presenter
        try:
            ok = bool(instance.start({}))
        except Exception as exc:
            entry.lifecycle = ServiceLifecycle.ERROR
            raise DomainError(f"Service '{service_id}' start() failed: {exc}") from exc

        entry.lifecycle = ServiceLifecycle.RUNNING if ok else ServiceLifecycle.ERROR
        if not ok:
            raise DomainError(f"Service '{service_id}' start() returned False")

    def stop(self, service_id: str) -> None:
        """Останавливает сервис. Idempotent: если уже STOPPED — no-op.

        Паттерн повторяет ServicesPresenter.stop_service():
        1. Получить entry из registry.
        2. Если instance не в кэше — синхронизировать lifecycle → STOPPED без вызова stop().
        3. Иначе instance.stop() — остановка.
        4. entry.lifecycle = STOPPED (или ERROR при ошибке).

        Args:
            service_id: Уникальное имя сервиса.

        Raises:
            DomainError: если service_id неизвестен.
            DomainError: если stop() провалился.
        """
        entry = self._registry.get(service_id)
        if entry is None:
            raise DomainError(f"Unknown service: {service_id}")

        # Idempotent: уже STOPPED — no-op
        if entry.lifecycle == ServiceLifecycle.STOPPED:
            logger.debug("ServiceManagerFromRegistry: stop(%s) — already STOPPED, no-op", service_id)
            return

        instance = self._instances.get(service_id)
        if instance is None:
            # Нечего останавливать — синхронизируем lifecycle
            entry.lifecycle = ServiceLifecycle.STOPPED
            return

        try:
            ok = bool(instance.stop())
        except Exception as exc:
            entry.lifecycle = ServiceLifecycle.ERROR
            raise DomainError(f"Service '{service_id}' stop() failed: {exc}") from exc

        entry.lifecycle = ServiceLifecycle.STOPPED if ok else ServiceLifecycle.ERROR
        if not ok:
            raise DomainError(f"Service '{service_id}' stop() returned False")

    def restart(self, service_id: str) -> None:
        """stop() + start().

        Args:
            service_id: Уникальное имя сервиса.

        Raises:
            DomainError: если service_id неизвестен или stop/start провалились.
        """
        self.stop(service_id)
        self.start(service_id)

    def get_lifecycle(self, service_id: str) -> ServiceLifecycle:
        """Текущий lifecycle статус сервиса.

        Args:
            service_id: Уникальное имя сервиса.

        Returns:
            ServiceLifecycle enum value.

        Raises:
            DomainError: если service_id неизвестен.
        """
        entry = self._registry.get(service_id)
        if entry is None:
            raise DomainError(f"Unknown service: {service_id}")
        return entry.lifecycle


# Backward-compatible alias (Phase B / C.1 legacy)
ServiceCatalogFromRegistry = ServiceManagerFromRegistry

# Проверка structural subtyping (import-time)
_: ServiceManager = ServiceManagerFromRegistry.__new__(ServiceManagerFromRegistry)  # type: ignore[assignment]

__all__ = [
    "ServiceManagerFromRegistry",
    "ServiceCatalogFromRegistry",
]
