# multiprocess_prototype_v3/frontend/widgets/tabs_setting/cropped_regions_tab/widget.py
"""Вкладка ROI: оболочка — placeholder или CroppedRegionsPanelWidget."""
from __future__ import annotations

from frontend_module.widgets.tabs import PanelTabBase

from ...cropped_regions_widget import CroppedRegionsPanelWidget
from ...cropped_regions_widget.schemas import CroppedRegionsTabUiConfig


class CroppedRegionsTabWidget(PanelTabBase[CroppedRegionsPanelWidget, CroppedRegionsTabUiConfig]):
    """Тонкая вкладка: RegisterBindingContext + фиче-виджет BaseWidget."""

    _panel_class = CroppedRegionsPanelWidget
    _config_class = CroppedRegionsTabUiConfig
    _placeholder_name = "Области (ROI)"
