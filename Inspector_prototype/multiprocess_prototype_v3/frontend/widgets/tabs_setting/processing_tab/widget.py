# multiprocess_prototype_v3/frontend/widgets/tabs_setting/processing_tab/widget.py
"""Вкладка обработки: оболочка — placeholder или ProcessingPanelWidget."""
from __future__ import annotations

from multiprocess_framework.modules.frontend_module.widgets.tabs import PanelTabBase

from ...processing.processing_panel_widget import ProcessingPanelWidget
from ...processing.processing_panel_widget.schemas import ProcessingTabUiConfig


class ProcessingTabWidget(PanelTabBase[ProcessingPanelWidget, ProcessingTabUiConfig]):
    """Тонкая вкладка: RegisterBindingContext + фиче-виджет BaseWidget."""

    _panel_class = ProcessingPanelWidget
    _config_class = ProcessingTabUiConfig
    _placeholder_name = "Обработка"
