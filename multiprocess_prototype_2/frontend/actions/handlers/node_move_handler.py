"""NodeMoveHandler — apply/revert перемещения ноды (GUI-only, без IPC)."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.actions.schemas import Action

logger = logging.getLogger(__name__)


class NodeMoveHandler:
    """Обработчик перемещения ноды: GUI-only, без IPC.

    apply: вызывает on_position_changed(node_id, x, y) с координатами из forward_patch.
    revert: вызывает on_position_changed(node_id, x, y) с координатами из backward_patch.
    """

    def __init__(
        self,
        on_position_changed: Callable[[str, float, float], None] | None = None,
    ) -> None:
        self._on_position_changed = on_position_changed

    def apply(self, action: "Action", rm: Any) -> None:
        """Переместить ноду в позицию из forward_patch."""
        node_id = action.forward_patch.get("node_id", "")
        x = action.forward_patch.get("x", 0.0)
        y = action.forward_patch.get("y", 0.0)
        if not node_id:
            logger.warning("node_move apply: node_id пуст")
            return
        if self._on_position_changed:
            self._on_position_changed(node_id, x, y)

    def revert(self, action: "Action", rm: Any) -> None:
        """Вернуть ноду в предыдущую позицию из backward_patch."""
        node_id = action.backward_patch.get("node_id", "")
        x = action.backward_patch.get("x", 0.0)
        y = action.backward_patch.get("y", 0.0)
        if not node_id:
            logger.warning("node_move revert: node_id пуст")
            return
        if self._on_position_changed:
            self._on_position_changed(node_id, x, y)
