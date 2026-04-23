"""
RegionActionHandler — обработчик REGION_ADD / REGION_REMOVE действий.

apply():  записывает forward_patch["pipeline_after"] как vision_pipeline регистра.
revert(): записывает backward_patch["pipeline_before"] как vision_pipeline регистра.

Guard: если register_name отсутствует или ключ pipeline не найден — log warning, return.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import IRegistersManagerGui
    from ..schemas import Action

logger = logging.getLogger(__name__)


class RegionActionHandler:
    """
    Обработчик действий типа REGION_ADD и REGION_REMOVE.

    Оба типа имеют одинаковую структуру патчей:
    - forward_patch["pipeline_after"]  — состояние vision_pipeline после операции
    - backward_patch["pipeline_before"] — состояние vision_pipeline до операции
    """

    def apply(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Применить: записать pipeline_after в регистр как vision_pipeline."""
        if not self._validate(action, "apply"):
            return

        pipeline_after = action.forward_patch.get("pipeline_after")
        if pipeline_after is None:
            logger.warning(
                "RegionActionHandler.apply: pipeline_after отсутствует, action_id=%s",
                action.action_id,
            )
            return

        rm.set_field_value(action.register_name, "vision_pipeline", pipeline_after)

    def revert(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Откатить: записать pipeline_before в регистр как vision_pipeline."""
        if not self._validate(action, "revert"):
            return

        pipeline_before = action.backward_patch.get("pipeline_before")
        if pipeline_before is None:
            logger.warning(
                "RegionActionHandler.revert: pipeline_before отсутствует, action_id=%s",
                action.action_id,
            )
            return

        rm.set_field_value(action.register_name, "vision_pipeline", pipeline_before)

    @staticmethod
    def _validate(action: Action, operation: str) -> bool:
        """Проверить наличие register_name."""
        if not action.register_name:
            logger.warning(
                "RegionActionHandler.%s: register_name отсутствует, action_id=%s",
                operation,
                action.action_id,
            )
            return False
        return True
