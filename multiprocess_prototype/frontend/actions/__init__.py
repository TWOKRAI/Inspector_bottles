"""actions — шина действий v2 с undo/redo.

Переиспользует FW ActionBus, Action, ActionBuilder.
V2 добавляет: handlers, builder extension, bus factory.
"""
from multiprocess_framework.modules.frontend_module.actions.bus import ActionBus
from multiprocess_framework.modules.frontend_module.actions.schemas import Action
from multiprocess_framework.modules.frontend_module.actions.builder import ActionBuilder

from .action_types import (
    FIELD_SET,
    NODE_MOVE,
    PROCESS_ADD,
    PROCESS_REMOVE,
    RECIPE_APPLY,
    WIRE_ADD,
    WIRE_REMOVE,
)
from .builder import V2ActionBuilder
from .bus_factory import create_action_bus
from .handlers.topology_mutation_handler import TopologyMutationHandler
from .handlers.node_move_handler import NodeMoveHandler

__all__ = [
    "ActionBus",
    "Action",
    "ActionBuilder",
    "V2ActionBuilder",
    "create_action_bus",
    "FIELD_SET",
    "RECIPE_APPLY",
    "PROCESS_ADD",
    "PROCESS_REMOVE",
    "WIRE_ADD",
    "WIRE_REMOVE",
    "NODE_MOVE",
    "TopologyMutationHandler",
    "NodeMoveHandler",
]
