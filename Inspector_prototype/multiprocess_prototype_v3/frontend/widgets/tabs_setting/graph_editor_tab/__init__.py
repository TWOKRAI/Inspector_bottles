"""Вкладка «Граф» — графовый редактор цепочки обработки."""
from __future__ import annotations

from .schemas import GraphEditorTabConfig, default_tab_item
from .widget import GraphEditorTabWidget

__all__ = ["GraphEditorTabConfig", "GraphEditorTabWidget", "default_tab_item"]
