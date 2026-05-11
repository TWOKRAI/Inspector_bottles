"""Фабрика ActionBus для v2 — создаёт шину с зарегистрированными handlers.

Phase 12: опциональный topology_bridge для IPC-интеграции.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.actions_module.bus import ActionBus

from .action_types import (
    FIELD_SET,
    NODE_MOVE,
    PROCESS_ADD,
    PROCESS_REMOVE,
    RECIPE_APPLY,
    WIRE_ADD,
    WIRE_REMOVE,
)
from .handlers import FieldSetHandler, NodeMoveHandler, RecipeApplyHandler, TopologyMutationHandler

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.bridge.topology_bridge import TopologyBridge
    from multiprocess_prototype.frontend.topology_holder import TopologyHolder


def create_action_bus(
    rm: Any,
    topology_holder: "TopologyHolder",
    *,
    topology_bridge: "TopologyBridge | None" = None,
    max_history: int = 50,
) -> ActionBus:
    """Создать ActionBus v2 с handlers для field_set и recipe_apply.

    Args:
        rm: RegistersManager (совместим с IRegistersManagerGui).
        topology_holder: TopologyHolder для recipe_apply handler.
        topology_bridge: TopologyBridge для IPC-интеграции (Phase 12, опционально).
        max_history: максимальный размер undo-стека (по умолчанию 50).

    Returns:
        Готовый к использованию ActionBus.
    """
    bus = ActionBus(rm, max_history=max_history)
    bus.register_handler(FIELD_SET, FieldSetHandler(topology_bridge=topology_bridge))
    bus.register_handler(RECIPE_APPLY, RecipeApplyHandler(topology_holder))

    # Phase 13: topology mutation handlers
    topo_handler = TopologyMutationHandler(
        topology_holder, topology_bridge=topology_bridge,
    )
    bus.register_handler(PROCESS_ADD, topo_handler)
    bus.register_handler(PROCESS_REMOVE, topo_handler)
    bus.register_handler(WIRE_ADD, topo_handler)
    bus.register_handler(WIRE_REMOVE, topo_handler)

    # Phase 13: node move handler (GUI-only, callback устанавливается через set_callback)
    node_move_handler = NodeMoveHandler()
    bus.register_handler(NODE_MOVE, node_move_handler)
    bus.node_move_handler = node_move_handler  # для post-init конфигурации
    return bus
