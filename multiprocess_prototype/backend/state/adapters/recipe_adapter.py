"""recipe_adapter.py — RecipeStateAdapter: двусторонняя синхронизация RecipeManager ↔ StateProxy.

Наследует StateAdapterBase и реализует паттерн anti-loop:
- при state.recipes.active → RecipeManager.set_active(slug)
- при RecipeManager.set_active → state.recipes.active обновляется через sync_domain_to_state

Anti-loop: _mark_pending перед state_proxy.set(), _check_and_clear_pending в callback —
предотвращает эхо-зацикливание (паттерн из StateAdapterBase / RegistersStateAdapter).

Breaking change (Task 5.5): старый RecipeAdapter (list_slots/get_slot/save_slot/delete_slot)
удалён. GUI-виджеты tabs/recipes/ будут переписаны в Task 5.7.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.5
"""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.state_store_module import Delta
from multiprocess_framework.modules.state_store_module.adapters import StateAdapterBase


# Путь в StateStore для активного рецепта
_PATH_ACTIVE = "recipes.active"
# Путь в StateStore для списка доступных рецептов
_PATH_AVAILABLE = "recipes.available"


class RecipeStateAdapter(StateAdapterBase):
    """Двусторонняя синхронизация RecipeManager ↔ StateProxy.

    Направление 1 (state→domain):
        StateProxy.subscribe("recipes.active") → _on_state_active_changed
        → RecipeManager.set_active(slug)

    Направление 2 (domain→state):
        sync_domain_to_state() → state_proxy.set("recipes.active", active)
                                + state_proxy.set("recipes.available", slugs)

    Anti-loop:
        Перед set() в StateProxy → _mark_pending(path).
        В callback → _check_and_clear_pending(path): True = эхо, skip.

    Args:
        recipe_manager: RecipeManager (application-обёртка над RecipeEngine).
        state_proxy: GuiStateProxy или StateProxy (опционален, можно bind() позже).
        logger: менеджер логирования (LoggerManager или совместимый, опционален).
        stats: менеджер статистики (опционален).
        error: менеджер ошибок (опционален).
    """

    def __init__(
        self,
        recipe_manager: Any,
        state_proxy: Any | None = None,
        logger: Any | None = None,
        stats: Any | None = None,
        error: Any | None = None,
    ) -> None:
        super().__init__(state_proxy=state_proxy, logger=logger, stats=stats, error=error)
        self._recipe_manager = recipe_manager

    # -------------------------------------------------------------------
    # StateAdapterBase — реализация абстрактных методов
    # -------------------------------------------------------------------

    def _subscribe_all(self) -> None:
        """Создать подписку на state.recipes.active → _on_state_active_changed.

        Вызывается базовым классом из connect().
        """
        sub_id = self._proxy.subscribe(
            _PATH_ACTIVE,
            self._on_state_active_changed,
        )
        self._sub_ids.append(sub_id)
        self._log_info(
            "RecipeStateAdapter: подписка создана, path=%s, sub_id=%s",
            _PATH_ACTIVE,
            sub_id,
        )

    def _unsubscribe_all(self) -> None:
        """Отменить все подписки на StateProxy.

        Вызывается базовым классом из disconnect().
        """
        for sub_id in self._sub_ids:
            self._proxy.unsubscribe(sub_id)
        self._log_info("RecipeStateAdapter: подписки отменены, sub_ids=%d", len(self._sub_ids))

    def sync_domain_to_state(self) -> None:
        """Синхронизировать текущее состояние RecipeManager → StateProxy.

        Публикует:
        - state.recipes.active = recipe_manager.get_active()
        - state.recipes.available = recipe_manager.list()

        Использует _mark_pending для предотвращения echo-loop.
        """
        if self._proxy is None:
            self._log_warning("RecipeStateAdapter: sync_domain_to_state — нет proxy")
            return

        # Публикуем активный рецепт
        active = self._recipe_manager.get_active()
        self._mark_pending(_PATH_ACTIVE)
        try:
            self._proxy.set(_PATH_ACTIVE, active)
        except Exception:
            # Если set упал — убираем pending чтобы не блокировать обратный путь
            self._pending_paths.discard(_PATH_ACTIVE)

        # Публикуем список доступных рецептов
        available = self._recipe_manager.list()
        self._mark_pending(_PATH_AVAILABLE)
        try:
            self._proxy.set(_PATH_AVAILABLE, available)
        except Exception:
            self._pending_paths.discard(_PATH_AVAILABLE)

        self._log_info(
            "RecipeStateAdapter: sync_domain_to_state — active=%s, available=%d",
            active,
            len(available) if available else 0,
        )

    def sync_state_to_domain(self) -> None:
        """Синхронизировать state.recipes.active → RecipeManager.

        Читает активный slug из StateProxy и вызывает set_active.
        Если slug is None — ничего не делает.
        """
        if self._proxy is None:
            self._log_warning("RecipeStateAdapter: sync_state_to_domain — нет proxy")
            return

        slug = self._proxy.get(_PATH_ACTIVE)
        if slug is None:
            self._log_info("RecipeStateAdapter: sync_state_to_domain — active=None, пропуск")
            return

        result = self._recipe_manager.set_active(slug)
        if not result:
            self._log_warning(
                "RecipeStateAdapter: sync_state_to_domain — set_active('%s') вернул False (рецепт не найден?)",
                slug,
            )
        else:
            self._log_info("RecipeStateAdapter: sync_state_to_domain — активирован рецепт '%s'", slug)

    # -------------------------------------------------------------------
    # Callback: StateProxy → RecipeManager
    # -------------------------------------------------------------------

    def _on_state_active_changed(self, deltas: list[Delta]) -> None:
        """Callback при изменении state.recipes.active в StateProxy.

        Для каждой дельты с path == "recipes.active":
        - Проверяет anti-loop (_check_and_clear_pending).
        - Если new_value is None — пропускает.
        - Иначе вызывает recipe_manager.set_active(new_value).

        Args:
            deltas: список Delta от StateProxy.
        """
        for delta in deltas:
            if delta.path != _PATH_ACTIVE:
                continue

            # Anti-loop: если мы сами инициировали это изменение — пропускаем
            if self._check_and_clear_pending(delta.path):
                continue

            # Пропускаем None (сброс активного рецепта)
            if delta.new_value is None:
                self._log_info("RecipeStateAdapter: delta new_value=None — пропуск set_active")
                continue

            result = self._recipe_manager.set_active(delta.new_value)
            if not result:
                self._log_warning(
                    "RecipeStateAdapter: set_active('%s') вернул False (рецепт не найден?)",
                    delta.new_value,
                )
            else:
                self._log_info(
                    "RecipeStateAdapter: state→domain — активирован рецепт '%s'",
                    delta.new_value,
                )


__all__ = ["RecipeStateAdapter"]
