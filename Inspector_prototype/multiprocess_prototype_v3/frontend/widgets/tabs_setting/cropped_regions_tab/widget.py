# multiprocess_prototype_v3/frontend/widgets/tabs_setting/cropped_regions_tab/widget.py
"""Вкладка ROI: оболочка — placeholder или CroppedRegionsPanelWidget."""

from __future__ import annotations

from typing import Any

from frontend_module.widgets.tabs import PanelTabBase

from ...cropped_regions_widget import CroppedRegionsPanelWidget
from ...cropped_regions_widget.schemas import CroppedRegionsTabUiConfig


class CroppedRegionsTabWidget(PanelTabBase[CroppedRegionsPanelWidget, CroppedRegionsTabUiConfig]):
    """Тонкая вкладка: RegisterBindingContext + фиче-виджет BaseWidget."""

    _panel_class = CroppedRegionsPanelWidget
    _config_class = CroppedRegionsTabUiConfig
    _placeholder_name = "Области (ROI)"

    def _build_panel_kwargs(self) -> dict[str, Any]:
        """Прокинуть camera_registry и action_bus из tab kwargs в панель."""
        kw: dict[str, Any] = {}
        cr = self._extra_kwargs.get("camera_registry")
        if cr is not None:
            kw["camera_registry"] = cr
        ab = self._extra_kwargs.get("action_bus")
        if ab is not None:
            kw["action_bus"] = ab
        return kw
