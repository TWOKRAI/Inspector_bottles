"""
FieldSetHandler — обработчик FIELD_SET действий.

apply():  устанавливает forward_patch["value"] через rm.set_field_value.
revert(): устанавливает backward_patch["value"] через rm.set_field_value.

Guard: если register_name или field_name отсутствует — log warning, return.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import IRegistersManagerGui
    from ..schemas import Action

logger = logging.getLogger(__name__)


class FieldSetHandler:
    """Обработчик действий типа FIELD_SET (изменение поля регистра)."""

    def apply(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Применить: записать forward_patch['value'] в регистр."""
        if not self._validate(action, "apply"):
            return

        value = action.forward_patch.get("value")
        rm.set_field_value(action.register_name, action.field_name, value)

    def revert(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Откатить: записать backward_patch['value'] в регистр."""
        if not self._validate(action, "revert"):
            return

        value = action.backward_patch.get("value")
        rm.set_field_value(action.register_name, action.field_name, value)

    @staticmethod
    def _validate(action: Action, operation: str) -> bool:
        """Проверить наличие register_name и field_name."""
        if not action.register_name:
            logger.warning(
                "FieldSetHandler.%s: register_name отсутствует, action_id=%s",
                operation,
                action.action_id,
            )
            return False
        if not action.field_name:
            logger.warning(
                "FieldSetHandler.%s: field_name отсутствует, action_id=%s",
                operation,
                action.action_id,
            )
            return False
        return True
