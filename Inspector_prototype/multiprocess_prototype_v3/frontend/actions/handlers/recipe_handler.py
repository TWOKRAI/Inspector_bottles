"""
RecipeSwitchHandler — обработчик RECIPE_SWITCH действий.

apply():  применить forward_patch["snapshot"] — записать каждое поле в регистр через rm.
revert(): применить backward_patch["snapshot"] — откатить к снимку до переключения.

Snapshot format: {register_name: {field_name: value}} — полный снимок всех затронутых регистров.

Аналог ProfileSwitchHandler, но для рецептов (slot-based).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..bus import IRegistersManagerGui
    from ..schemas import Action

logger = logging.getLogger(__name__)


class RecipeSwitchHandler:
    """Обработчик действий типа RECIPE_SWITCH (переключение рецепта).

    Snapshot-based undo/redo: применяет снимок полей регистров целиком,
    не вызывая switch-логику повторно (только при undo/redo).
    """

    def apply(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Применить forward_patch["snapshot"] к регистрам."""
        snapshot = action.forward_patch.get("snapshot")
        if snapshot is None:
            logger.warning(
                "RecipeSwitchHandler.apply: snapshot отсутствует в forward_patch, action_id=%s",
                action.action_id,
            )
            return
        self._apply_snapshot(snapshot, rm, "apply", action.action_id)

    def revert(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Откатить: применить backward_patch["snapshot"] к регистрам."""
        snapshot = action.backward_patch.get("snapshot")
        if snapshot is None:
            logger.warning(
                "RecipeSwitchHandler.revert: snapshot отсутствует в backward_patch, action_id=%s",
                action.action_id,
            )
            return
        self._apply_snapshot(snapshot, rm, "revert", action.action_id)

    @staticmethod
    def _apply_snapshot(
        snapshot: Any,
        rm: IRegistersManagerGui,
        operation: str,
        action_id: str,
    ) -> None:
        """Записать snapshot в регистры через rm.set_field_value.

        Поддерживает два формата snapshot:
        - {register_name: {field_name: value}} — полный (multi-register)
        - {field_name: value} — плоский (один регистр)
        """
        if not isinstance(snapshot, dict):
            logger.warning(
                "RecipeSwitchHandler.%s: snapshot не является dict, action_id=%s",
                operation,
                action_id,
            )
            return

        # Определяем формат: если значения — dict, то это multi-register формат
        is_multi_register = any(isinstance(v, dict) for v in snapshot.values())

        if is_multi_register:
            # {register_name: {field_name: value}}
            _apply_multi_register_snapshot(snapshot, rm, operation, action_id)
        else:
            logger.warning(
                "RecipeSwitchHandler.%s: плоский snapshot неожиданен для рецепта, "
                "пропускаем, action_id=%s",
                operation,
                action_id,
            )


def _apply_multi_register_snapshot(
    snapshot: dict[str, Any],
    rm: IRegistersManagerGui,
    operation: str,
    action_id: str,
) -> None:
    """Применить многорегистровый снимок {register_name: {field_name: value}}."""
    for register_name, fields in snapshot.items():
        if not isinstance(fields, dict):
            logger.warning(
                "RecipeSwitchHandler.%s: поля регистра '%s' не dict, action_id=%s",
                operation,
                register_name,
                action_id,
            )
            continue
        for field_name, value in fields.items():
            ok, err = rm.set_field_value(register_name, field_name, value)
            if not ok:
                logger.warning(
                    "RecipeSwitchHandler.%s: set_field_value(%s, %s) вернул ошибку: %s, action_id=%s",
                    operation,
                    register_name,
                    field_name,
                    err,
                    action_id,
                )
