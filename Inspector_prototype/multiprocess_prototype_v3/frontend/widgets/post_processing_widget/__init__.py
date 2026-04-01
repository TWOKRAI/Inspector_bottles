# multiprocess_prototype/frontend/widgets/post_processing_widget/
"""Постобработка: регионы просмотра по камерам (BaseWidget + MVP)."""

from __future__ import annotations

from .panel_widget import PostProcessingPanelWidget
from .schemas import PostProcessingTabUiConfig, default_tab_item

__all__ = [
    "PostProcessingPanelWidget",
    "PostProcessingTabUiConfig",
    "default_tab_item",
]
