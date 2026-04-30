"""Router-топология: схемы и трансформация Pipeline → RouterTopology.

Публичный API:
    ChannelSpec       — описание одного канала Router
    EdgeSpec          — описание одного ребра DAG
    RouterTopology    — полное описание router-топологии
    to_router_topology — Pipeline → RouterTopology (чистая функция)
    apply_topology    — императивное применение топологии к Router
    ApplyResult       — статистика apply_topology
"""

from .builder import (
    ChannelSpec,
    EdgeSpec,
    RouterTopology,
    to_router_topology,
)
from .registrar import ApplyResult, apply_topology

__all__ = [
    "ChannelSpec",
    "EdgeSpec",
    "RouterTopology",
    "to_router_topology",
    "apply_topology",
    "ApplyResult",
]
