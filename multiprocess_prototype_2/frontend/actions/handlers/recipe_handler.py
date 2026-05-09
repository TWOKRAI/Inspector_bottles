"""RecipeApplyHandler — apply/revert замены topology при применении рецепта."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_framework.modules.frontend_module.actions.schemas import Action
    from multiprocess_prototype_2.frontend.topology_holder import TopologyHolder

logger = logging.getLogger(__name__)


class RecipeApplyHandler:
    """Обработчик recipe_apply: заменяет topology через TopologyHolder.

    apply: устанавливает topology из forward_patch.
    revert: восстанавливает topology из backward_patch (undo).
    """

    def __init__(self, topology_holder: "TopologyHolder") -> None:
        self._holder = topology_holder

    def apply(self, action: "Action", rm: Any) -> None:
        """Применить topology из рецепта (forward_patch)."""
        topology = action.forward_patch.get("topology", {})
        if topology:
            self._holder.set_topology(topology)
        else:
            logger.warning("recipe_apply apply: topology пуст в forward_patch")

    def revert(self, action: "Action", rm: Any) -> None:
        """Восстановить предыдущую topology (backward_patch)."""
        topology = action.backward_patch.get("topology", {})
        if topology:
            self._holder.set_topology(topology)
        else:
            logger.warning("recipe_apply revert: topology пуст в backward_patch")
