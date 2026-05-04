"""canvas — NodeGraphQt канвас для визуального конструктора межпроцессных связей."""

from .plugin_process_node import PROCESS_NODE_TYPE, PluginProcessNode
from .shm_route_node import ROUTE_NODE_TYPE, ShmRouteNode

__all__ = [
    "PluginProcessNode",
    "PROCESS_NODE_TYPE",
    "ShmRouteNode",
    "ROUTE_NODE_TYPE",
]
