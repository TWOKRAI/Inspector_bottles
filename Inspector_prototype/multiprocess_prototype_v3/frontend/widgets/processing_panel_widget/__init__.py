# multiprocess_prototype_v3/frontend/widgets/processing_panel_widget/
"""Изолированный виджет: панель обработки (BaseWidget + контролы регистров)."""

from .panel_widget import ProcessingPanelWidget
from .presenter import ProcessingPanelPresenter
from .model import ProcessingPanelModel
from .schemas import ProcessingTabUiConfig, default_tab_item

__all__ = [
    "ProcessingPanelModel",
    "ProcessingPanelPresenter",
    "ProcessingPanelWidget",
    "ProcessingTabUiConfig",
    "default_tab_item",
]
