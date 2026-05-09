"""frontend_module.graph — DAG-алгоритмы и автоматическая раскладка графа.

Публичный API:
- dag_utils: has_cycle, topological_sort, validate_port_compatibility, find_connected_edges
- layout: auto_layout
"""
from __future__ import annotations

from .dag_utils import (
    find_connected_edges,
    has_cycle,
    topological_sort,
    validate_port_compatibility,
)
from .layout import auto_layout

__all__ = [
    "has_cycle",
    "topological_sort",
    "validate_port_compatibility",
    "find_connected_edges",
    "auto_layout",
]
