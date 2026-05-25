"""service_state_adapter.py -- Двусторонняя синхронизация ServiceRegistry <-> state.services.*.

Подписывается на services.*.status через StateProxy и обеспечивает:
- sync_domain_to_state(): запись lifecycle всех сервисов из registry в state-дерево
- sync_state_to_domain(): чтение state-дерева и обновление lifecycle в registry
- _on_state_deltas(): callback на изменения -- обновляет ServiceEntry.lifecycle
  с anti-loop защитой через _mark_pending / _check_and_clear_pending

Паттерны путей:
    services.{name}.status  -- lifecycle сервиса: unregistered | ready | running | stopped | error

Refs: plans/prototype-skeleton-2026-05/phase-3-service-registry.md Task 3.5
"""

from __future__ import annotations

import re
from typing import Any

from multiprocess_framework.modules.service_module import (
    ServiceLifecycle,
    ServiceRegistry,
)
from multiprocess_framework.modules.state_store_module import Delta
from multiprocess_framework.modules.state_store_module.adapters import StateAdapterBase
from multiprocess_prototype.backend.state.schema import service_status_path

# Regex для разбора пути services.{name}.status
_SERVICE_STATUS_RE = re.compile(r"^services\.([^.]+)\.status$")


class ServiceStateAdapter(StateAdapterBase):
    """Адаптер сервисов: синхронизация ServiceRegistry <-> state.services.*.

    Подписывается на ``services.*.status`` через StateProxy.
    При получении дельт обновляет lifecycle в ServiceRegistry (anti-loop).

    Пример использования::

        registry = ServiceRegistry()
        adapter = ServiceStateAdapter(registry=registry)
        adapter.bind(state_proxy)
        adapter.connect()
        adapter.sync_domain_to_state()  # записать текущие lifecycle в state

    Args:
        registry: экземпляр ServiceRegistry (singleton).
        state_proxy: StateProxy или GuiStateProxy (опционален, можно bind() позже).
        logger: менеджер логирования (LoggerManager или совместимый).
        stats: менеджер статистики.
        error: менеджер ошибок.
    """

    def __init__(
        self,
        registry: ServiceRegistry,
        state_proxy: Any | None = None,
        logger: Any | None = None,
        stats: Any | None = None,
        error: Any | None = None,
    ) -> None:
        super().__init__(state_proxy=state_proxy, logger=logger, stats=stats, error=error)
        self._registry = registry

    # -------------------------------------------------------------------
    # StateAdapterBase -- реализация абстрактных методов
    # -------------------------------------------------------------------

    def _subscribe_all(self) -> None:
        """Подписаться на services.*.status через StateProxy.

        Вызывается базовым классом из connect().
        """
        sub_id = self._proxy.subscribe(
            "services.*.status",
            self._on_state_deltas,
            exclude_self=False,
        )
        self._sub_ids.append(sub_id)
        self._log_info(
            "ServiceStateAdapter: подписан на services.*.status, sub_id=%s",
            sub_id,
        )

    def _unsubscribe_all(self) -> None:
        """Отписаться от StateProxy.

        Вызывается базовым классом из disconnect().
        """
        for sub_id in self._sub_ids:
            self._proxy.unsubscribe(sub_id)
        self._log_info("ServiceStateAdapter: подписки отменены")

    def sync_domain_to_state(self) -> None:
        """Записать lifecycle всех сервисов из registry -> StateProxy.

        Для каждого ServiceEntry вызывает proxy.set(services.<name>.status, lifecycle).
        Использует anti-loop: _mark_pending() ДО set(), чтобы callback
        _on_state_deltas() пропустил эхо.
        """
        if self._proxy is None:
            self._log_warning("ServiceStateAdapter: sync_domain_to_state -- нет proxy, пропуск")
            return

        for entry in self._registry.list():
            path = service_status_path(entry.name)
            try:
                self._mark_pending(path)
                self._proxy.set(path, entry.lifecycle.value)
            except Exception:
                # Не дали записать -- снимаем pending-флаг
                self._pending_paths.discard(path)
                self._log_error("ServiceStateAdapter: ошибка записи %s в state", path)

    def sync_state_to_domain(self) -> None:
        """Прочитать state.services.* -> обновить lifecycle в ServiceRegistry.

        Читает ветвь ``services`` целиком и для каждого известного в registry
        сервиса обновляет ``entry.lifecycle`` по значению ``status``.
        """
        if self._proxy is None:
            self._log_warning("ServiceStateAdapter: sync_state_to_domain -- нет proxy, пропуск")
            return

        services_branch = self._proxy.get("services") or {}
        for name, data in services_branch.items():
            entry = self._registry.get(name)
            if entry is None:
                continue
            status = (data or {}).get("status") if isinstance(data, dict) else None
            if status is None:
                continue
            try:
                entry.lifecycle = ServiceLifecycle(status)
            except ValueError:
                self._log_warning(
                    "ServiceStateAdapter: некорректный status '%s' для сервиса '%s'",
                    status,
                    name,
                )

    # -------------------------------------------------------------------
    # Callback от StateProxy
    # -------------------------------------------------------------------

    def _on_state_deltas(self, deltas: list[Delta]) -> None:
        """Callback для StateProxy.subscribe.

        Вызывается при изменениях services.*.status.
        Разбирает путь, проверяет anti-loop и обновляет lifecycle в registry.

        Args:
            deltas: список Delta от StateProxy.
        """
        for delta in deltas:
            # Anti-loop: пропускаем эхо собственных set() из sync_domain_to_state
            if self._check_and_clear_pending(delta.path):
                continue

            match = _SERVICE_STATUS_RE.match(delta.path)
            if match is None:
                continue

            name = match.group(1)
            entry = self._registry.get(name)
            if entry is None:
                # Неизвестный сервис -- тихо пропускаем
                continue

            try:
                entry.lifecycle = ServiceLifecycle(delta.new_value)
            except ValueError:
                # Некорректное значение status в state -- игнорируем
                self._log_warning(
                    "ServiceStateAdapter: некорректный status '%s' для '%s' из state",
                    delta.new_value,
                    name,
                )


__all__ = ["ServiceStateAdapter"]
