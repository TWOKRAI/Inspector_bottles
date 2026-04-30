"""
ChainActionHandler — обработчик STEP_ADD / STEP_REMOVE / STEP_MODIFY / STEP_REORDER.

Работает с nodes-снимками из forward_patch/backward_patch.
Записывает nodes_snapshot в vision_pipeline регистра через rm.set_field_value (если данные доступны).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import IRegistersManagerGui
    from ..schemas import Action

logger = logging.getLogger(__name__)


class ChainActionHandler:
    """Обработчик STEP_* действий.

    Для STEP_ADD/REMOVE/REORDER: записывает nodes_snapshot_after/before в register.
    Для STEP_MODIFY: записывает node_after/before в register.

    Если action содержит pipeline_after/pipeline_before — пишет в rm.set_field_value
    как полный vision_pipeline (для undo/redo через register). Иначе — log warning.
    """

    def apply(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Применить: записать forward_patch в регистр."""
        fp = action.forward_patch

        # Если есть pipeline_after — записать как vision_pipeline (полная интеграция)
        pipeline_after = fp.get("pipeline_after")
        if pipeline_after is not None and action.register_name:
            rm.set_field_value(action.register_name, "vision_pipeline", pipeline_after)
            return

        # Если есть nodes_snapshot_after — записать как nodes
        nodes_after = fp.get("nodes_snapshot_after") or fp.get("nodes_after")
        if nodes_after is not None and action.register_name:
            rm.set_field_value(action.register_name, "vision_pipeline", nodes_after)
            return

        # STEP_MODIFY: node_after содержит данные одного узла — не пишем в pipeline целиком
        if fp.get("node_after") is not None:
            logger.debug(
                "ChainActionHandler.apply: STEP_MODIFY, node_after=%s (pipeline не обновляется)",
                fp.get("node_id"),
            )
            return

        logger.warning(
            "ChainActionHandler.apply: нет данных для записи, action_id=%s",
            action.action_id,
        )

    def revert(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Откатить: записать backward_patch в регистр."""
        bp = action.backward_patch

        # Если есть pipeline_before — записать как vision_pipeline
        pipeline_before = bp.get("pipeline_before")
        if pipeline_before is not None and action.register_name:
            rm.set_field_value(action.register_name, "vision_pipeline", pipeline_before)
            return

        # Если есть nodes_snapshot_before — записать как nodes
        nodes_before = bp.get("nodes_snapshot_before") or bp.get("nodes_before")
        if nodes_before is not None and action.register_name:
            rm.set_field_value(action.register_name, "vision_pipeline", nodes_before)
            return

        # STEP_MODIFY: node_before содержит данные одного узла
        if bp.get("node_before") is not None:
            logger.debug(
                "ChainActionHandler.revert: STEP_MODIFY, node_before=%s (pipeline не обновляется)",
                bp.get("node_id"),
            )
            return

        logger.warning(
            "ChainActionHandler.revert: нет данных для отката, action_id=%s",
            action.action_id,
        )
