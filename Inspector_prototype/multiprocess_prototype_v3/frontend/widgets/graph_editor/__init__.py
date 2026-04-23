"""Графовый редактор цепочки обработки (Phase 8)."""

from .catalog_palette import CatalogPalette
from .graph_scene import GraphScene
from .graph_view import GraphView
from .linearity_check import get_linearity_warning, is_linear
from .model import GraphEditorModel
from .provisional_edge import ProvisionalEdge
from .view_switch import ViewSwitchWidget

__all__ = [
    "CatalogPalette",
    "GraphEditorModel",
    "GraphScene",
    "GraphView",
    "ProvisionalEdge",
    "ViewSwitchWidget",
    "get_linearity_warning",
    "is_linear",
]
