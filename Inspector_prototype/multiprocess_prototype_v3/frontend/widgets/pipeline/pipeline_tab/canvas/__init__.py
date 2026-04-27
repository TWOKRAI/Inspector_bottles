"""Canvas-подпакет: граф-модель, адаптер NodeGraphQt, авто-раскладка, линейность."""

from .auto_layout import auto_layout
from .linearity_check import get_linearity_warning, is_linear
from .model import GraphEditorModel

__all__ = [
    "auto_layout",
    "get_linearity_warning",
    "is_linear",
    "GraphEditorModel",
]
