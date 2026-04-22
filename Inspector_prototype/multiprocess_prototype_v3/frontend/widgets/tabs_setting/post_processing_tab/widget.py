# multiprocess_prototype_v3/frontend/widgets/tabs_setting/post_processing_tab/widget.py
"""Вкладка постобработки: оболочка — placeholder или PostProcessingPanelWidget."""
from __future__ import annotations

from frontend_module.widgets.tabs import PanelTabBase

from ...post_processing_widget import PostProcessingPanelWidget
from ...post_processing_widget.schemas import PostProcessingTabUiConfig


class PostProcessingTabWidget(PanelTabBase[PostProcessingPanelWidget, PostProcessingTabUiConfig]):
    """Тонкая вкладка: RegisterBindingContext + фиче-виджет BaseWidget."""

    _panel_class = PostProcessingPanelWidget
    _config_class = PostProcessingTabUiConfig
    _placeholder_name = "Постобработка"
