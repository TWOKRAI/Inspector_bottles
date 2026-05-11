"""PreAuthGuard — блокирует мутации (WriteAction) до авторизации.

Использование:
    guard = PreAuthGuard(auth_state)
    bus.set_pre_execute_hook(guard.hook, on_blocked=guard.show_auth_required)

Определение WriteAction: action блокируется, если action.undoable == True
ИЛИ если action.action_type входит в WRITE_ACTION_TYPES.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from multiprocess_framework.modules.actions_module.schemas import Action
from multiprocess_prototype.frontend.actions.action_types import (
    FIELD_SET,
    PROCESS_ADD,
    PROCESS_REMOVE,
    RECIPE_APPLY,
    WIRE_ADD,
    WIRE_REMOVE,
)

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.state.auth_state import AuthState

logger = logging.getLogger(__name__)

# Типы действий, считающиеся мутацией (блокируются без авторизации)
WRITE_ACTION_TYPES: frozenset[str] = frozenset({
    FIELD_SET,
    RECIPE_APPLY,
    PROCESS_ADD,
    PROCESS_REMOVE,
    WIRE_ADD,
    WIRE_REMOVE,
})


class PreAuthGuard:
    """Хук для ActionBus: блокирует мутации до авторизации.

    Правило блокировки: action блокируется, если пользователь не авторизован
    И (action.undoable == True ИЛИ action.action_type входит в WRITE_ACTION_TYPES).
    Read-only действия (node_move и другие не-undoable вне WRITE_ACTION_TYPES) проходят.
    """

    def __init__(self, auth_state: "AuthState") -> None:
        self._auth_state = auth_state

    def hook(self, action: Action) -> bool:
        """True — разрешить выполнение, False — заблокировать.

        Авторизованный пользователь: всё разрешено.
        Неавторизованный: блокируются undoable-действия и action_type из WRITE_ACTION_TYPES.
        """
        if self._auth_state.is_authenticated:
            return True

        # Проверяем, является ли действие мутацией
        is_write = action.undoable or action.action_type in WRITE_ACTION_TYPES
        return not is_write

    def show_auth_required(self, action: Action) -> None:
        """Показать диалог «Требуется вход». Вызывается ActionBus при блокировке.

        Импорт QMessageBox выполняется лениво, чтобы PreAuthGuard был тестируем
        без Qt-окружения (hook() не требует Qt).
        """
        from PySide6.QtWidgets import QMessageBox

        description = action.description or action.action_type
        logger.info(
            "Действие заблокировано (требуется авторизация): %s", description
        )
        QMessageBox.information(
            None,
            "Требуется вход",
            f"Для выполнения действия «{description}» необходимо войти в систему.",
        )

    # ------------------------------------------------------------------
    # Обратная совместимость: on_blocked как псевдоним show_auth_required
    # ------------------------------------------------------------------

    def on_blocked(self, action: Action) -> None:
        """Псевдоним show_auth_required для обратной совместимости."""
        self.show_auth_required(action)
