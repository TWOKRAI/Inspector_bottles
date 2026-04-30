"""
DisplayActionHandler — обработчик DISPLAY_SUBSCRIBE / DISPLAY_UNSUBSCRIBE / LAYOUT_CHANGE.

DISPLAY_SUBSCRIBE/UNSUBSCRIBE: undoable=False, только логирование.
LAYOUT_CHANGE: undoable=True, apply/revert переключают подписки через display_router.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..bus import IRegistersManagerGui
    from ..schemas import Action

logger = logging.getLogger(__name__)


class DisplayActionHandler:
    """Обработчик display-действий.

    display_router инжектируется при создании. Может быть None,
    тогда handler только логирует (полезно для тестов).
    """

    def __init__(self, display_router: Any = None) -> None:
        self._display_router = display_router

    def apply(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Применить display-действие."""
        from ..schemas import ActionType

        if action.action_type == ActionType.LAYOUT_CHANGE:
            self._apply_layout(action, direction="forward")
        else:
            # DISPLAY_SUBSCRIBE / DISPLAY_UNSUBSCRIBE — command-type, только лог
            logger.debug(
                "DisplayActionHandler.apply: %s, source_ref=%s",
                action.action_type.value,
                action.forward_patch.get("source_ref", "?"),
            )

    def revert(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Откатить display-действие (только для LAYOUT_CHANGE)."""
        from ..schemas import ActionType

        if action.action_type == ActionType.LAYOUT_CHANGE:
            self._apply_layout(action, direction="backward")
        else:
            logger.debug(
                "DisplayActionHandler.revert: %s — undoable=False, revert не применяется",
                action.action_type.value,
            )

    def _apply_layout(self, action: Action, direction: str) -> None:
        """Применить/откатить смену раскладки — отписать все, подписать из snapshot."""
        if self._display_router is None:
            logger.warning(
                "DisplayActionHandler._apply_layout: display_router не установлен, action_id=%s",
                action.action_id,
            )
            return

        patch = action.forward_patch if direction == "forward" else action.backward_patch
        key = "subscriptions_after" if direction == "forward" else "subscriptions_before"
        subs = patch.get(key)
        if subs is None:
            logger.warning(
                "DisplayActionHandler._apply_layout: subscriptions отсутствуют, action_id=%s",
                action.action_id,
            )
            return

        # Отписать все текущие
        self._display_router.unsubscribe_all()

        # Подписать из snapshot
        for sub_data in subs:
            if hasattr(sub_data, "subscription_id"):
                # DisplaySubscription object
                self._display_router.subscribe(sub_data)
            elif isinstance(sub_data, dict):
                # Dict — нужно десериализовать
                from registers.display.schemas import DisplaySubscription

                try:
                    sub = DisplaySubscription(**sub_data)
                    self._display_router.subscribe(sub)
                except Exception:
                    logger.warning(
                        "Не удалось восстановить подписку из dict: %s",
                        sub_data,
                    )
