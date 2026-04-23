"""
GraphActionHandler — обработчик GRAPH_* действий графового редактора.

Поддерживает пять типов:
  - GRAPH_CONNECT    — добавление связи между узлами
  - GRAPH_DISCONNECT — удаление связи между узлами
  - GRAPH_NODE_ADD   — добавление узла в граф
  - GRAPH_NODE_REMOVE — удаление узла из графа
  - GRAPH_NODE_MOVE  — перемещение узла (позиция)

Паттерн аналогичен ChainActionHandler:
  - apply/revert для CONNECT, DISCONNECT, NODE_ADD, NODE_REMOVE:
    записывают nodes_after/nodes_before через rm.set_field_value
  - apply/revert для GRAPH_NODE_MOVE: только логируют координаты;
    позиция ноды обновляется через модель, presenter обновит UI.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..bus import IRegistersManagerGui
    from ..schemas import Action

from ..schemas import ActionType

logger = logging.getLogger(__name__)


class GraphActionHandler:
    """Обработчик GRAPH_* действий: connect, disconnect, node_add, node_remove, node_move."""

    def apply(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Применить действие: записать forward_patch в регистр.

        Для GRAPH_NODE_MOVE: только логируем новую позицию (модель обновляется через presenter).
        Для остальных GRAPH_*: записываем nodes_after в vision_pipeline регистра.
        """
        fp = action.forward_patch

        # GRAPH_NODE_MOVE — позиция хранится в patch, presenter обновит UI
        if action.action_type == ActionType.GRAPH_NODE_MOVE:
            logger.debug(
                "GraphActionHandler.apply: GRAPH_NODE_MOVE node_id=%s new_pos=%s",
                fp.get("node_id"),
                fp.get("new_pos"),
            )
            return

        # GRAPH_CONNECT / GRAPH_DISCONNECT / GRAPH_NODE_ADD / GRAPH_NODE_REMOVE
        nodes_after = fp.get("nodes_after")
        if nodes_after is not None and action.register_name:
            rm.set_field_value(action.register_name, "vision_pipeline", nodes_after)
            return

        logger.warning(
            "GraphActionHandler.apply: нет данных для записи, action_id=%s, action_type=%s",
            action.action_id,
            action.action_type,
        )

    def revert(self, action: Action, rm: IRegistersManagerGui) -> None:
        """Откатить действие: записать backward_patch в регистр.

        Для GRAPH_NODE_MOVE: только логируем старую позицию (presenter восстановит UI).
        Для остальных GRAPH_*: записываем nodes_before в vision_pipeline регистра.
        """
        bp = action.backward_patch

        # GRAPH_NODE_MOVE — восстанавливаем позицию через presenter, не через pipeline
        if action.action_type == ActionType.GRAPH_NODE_MOVE:
            logger.debug(
                "GraphActionHandler.revert: GRAPH_NODE_MOVE node_id=%s old_pos=%s",
                bp.get("node_id"),
                bp.get("old_pos"),
            )
            return

        # GRAPH_CONNECT / GRAPH_DISCONNECT / GRAPH_NODE_ADD / GRAPH_NODE_REMOVE
        nodes_before = bp.get("nodes_before")
        if nodes_before is not None and action.register_name:
            rm.set_field_value(action.register_name, "vision_pipeline", nodes_before)
            return

        logger.warning(
            "GraphActionHandler.revert: нет данных для отката, action_id=%s, action_type=%s",
            action.action_id,
            action.action_type,
        )
