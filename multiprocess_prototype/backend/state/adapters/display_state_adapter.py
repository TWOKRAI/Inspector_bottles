"""display_state_adapter.py -- Двусторонняя синхронизация DisplayRegistry <-> state.displays.*.

Подписывается на displays.*.status через StateProxy и обеспечивает:
- sync_domain_to_state(): запись config и status всех дисплеев из registry в state-дерево
- sync_state_to_domain(): Phase 4 -- no-op / минимальная реализация (только логирует)
- _on_state_deltas(): callback на изменения -- anti-loop защита через _mark_pending /
  _check_and_clear_pending; в Phase 4 только логирует (без действия), полная логика -- Phase 5.

Паттерны путей:
    displays.{id}.status  -- статус дисплея: "registered" (SHM ещё не открыт)
    displays.{id}.config  -- сериализованная конфигурация DisplayEntry

Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md Task 4.5
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from multiprocess_framework.modules.display_module import DisplayRegistry
from multiprocess_framework.modules.state_store_module import Delta
from multiprocess_framework.modules.state_store_module.adapters import StateAdapterBase
from multiprocess_prototype.backend.state.schema import (
    display_config_path,
    display_status_path,
)

# Regex для разбора пути displays.{id}.status
_DISPLAY_STATUS_RE = re.compile(r"^displays\.([^.]+)\.status$")


class DisplayStateAdapter(StateAdapterBase):
    """Адаптер дисплеев: синхронизация DisplayRegistry <-> state.displays.*.

    Подписывается на ``displays.*.status`` через StateProxy.
    При получении дельт -- логирует (Phase 4, полная логика в Phase 5).

    Пример использования::

        registry = DisplayRegistry()
        adapter = DisplayStateAdapter(registry=registry)
        adapter.bind(state_proxy)
        adapter.connect()
        adapter.sync_domain_to_state()  # записать config + status в state

    Args:
        registry: экземпляр DisplayRegistry (singleton).
        state_proxy: StateProxy или GuiStateProxy (опционален, можно bind() позже).
        logger: менеджер логирования (LoggerManager или совместимый).
        stats: менеджер статистики.
        error: менеджер ошибок.
    """

    def __init__(
        self,
        registry: DisplayRegistry,
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
        """Подписаться на displays.*.status через StateProxy.

        Вызывается базовым классом из connect().
        """
        sub_id = self._proxy.subscribe(
            "displays.*.status",
            self._on_state_deltas,
            exclude_self=False,
        )
        self._sub_ids.append(sub_id)
        self._log_info(
            "DisplayStateAdapter: подписан на displays.*.status, sub_id=%s",
            sub_id,
        )

    def _unsubscribe_all(self) -> None:
        """Отписаться от StateProxy.

        Вызывается базовым классом из disconnect().
        """
        for sub_id in self._sub_ids:
            self._proxy.unsubscribe(sub_id)
        self._log_info("DisplayStateAdapter: подписки отменены")

    def sync_domain_to_state(self) -> None:
        """Записать config и status всех дисплеев из registry -> StateProxy.

        Для каждого DisplayEntry вызывает:
            proxy.set(displays.<id>.status, "registered")
            proxy.set(displays.<id>.config, <entry dict>)
        Использует anti-loop: _mark_pending() ДО set(), чтобы callback
        _on_state_deltas() пропустил эхо собственного status-изменения.
        """
        if self._proxy is None:
            self._log_warning("DisplayStateAdapter: sync_domain_to_state -- нет proxy, пропуск")
            return

        for entry in self._registry.list():
            status_path = display_status_path(entry.id)
            config_path = display_config_path(entry.id)

            try:
                # Anti-loop для status: помечаем ДО записи
                self._mark_pending(status_path)
                self._proxy.set(status_path, "registered")
            except Exception:
                self._pending_paths.discard(status_path)
                self._log_error(
                    "DisplayStateAdapter: ошибка записи %s в state",
                    status_path,
                )

            try:
                # Config не вызывает рекурсивного callback (подписка только на *.status),
                # но mark_pending добавляем для единообразия и защиты от будущих подписок
                self._mark_pending(config_path)
                self._proxy.set(config_path, asdict(entry))
            except Exception:
                self._pending_paths.discard(config_path)
                self._log_error(
                    "DisplayStateAdapter: ошибка записи %s в state",
                    config_path,
                )

    def sync_state_to_domain(self) -> None:
        """Phase 4 -- минимальная реализация: читает state.displays.*, логирует.

        Без записи в registry -- у DisplayEntry нет поля lifecycle/status.
        Полная двусторонняя синхронизация -- Phase 5.
        """
        if self._proxy is None:
            self._log_warning("DisplayStateAdapter: sync_state_to_domain -- нет proxy, пропуск")
            return

        displays_branch = self._proxy.get("displays") or {}
        for display_id, data in displays_branch.items():
            status = (data or {}).get("status") if isinstance(data, dict) else None
            self._log_info(
                "DisplayStateAdapter: state.displays.%s.status = %s (sync_state_to_domain Phase 4, no-op)",
                display_id,
                status,
            )

    # -------------------------------------------------------------------
    # Callback от StateProxy
    # -------------------------------------------------------------------

    def _on_state_deltas(self, deltas: list[Delta]) -> None:
        """Callback для StateProxy.subscribe на displays.*.status.

        Phase 4: проверяет anti-loop, логирует изменения без действия.
        Phase 5 добавит обновление статуса дисплея.

        Args:
            deltas: список Delta от StateProxy.
        """
        for delta in deltas:
            # Anti-loop: пропускаем эхо собственных set() из sync_domain_to_state
            if self._check_and_clear_pending(delta.path):
                continue

            match = _DISPLAY_STATUS_RE.match(delta.path)
            if match is None:
                continue

            display_id = match.group(1)
            self._log_info(
                "DisplayStateAdapter: displays.%s.status изменён на '%s' (Phase 4: только лог, действий нет)",
                display_id,
                delta.new_value,
            )


__all__ = ["DisplayStateAdapter"]
