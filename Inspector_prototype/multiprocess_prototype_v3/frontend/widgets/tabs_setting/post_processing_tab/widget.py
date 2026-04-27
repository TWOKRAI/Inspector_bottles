# multiprocess_prototype_v3/frontend/widgets/tabs_setting/post_processing_tab/widget.py
"""Вкладка постобработки: оболочка — placeholder или PostProcessingPanelWidget."""

from __future__ import annotations

from typing import Any

from multiprocess_framework.modules.frontend_module.widgets.tabs import PanelTabBase

from ...processing.post_processing_widget import PostProcessingPanelWidget
from ...processing.post_processing_widget.schemas import PostProcessingTabUiConfig


class PostProcessingTabWidget(PanelTabBase[PostProcessingPanelWidget, PostProcessingTabUiConfig]):
    """Тонкая вкладка: RegisterBindingContext + фиче-виджет BaseWidget."""

    _panel_class = PostProcessingPanelWidget
    _config_class = PostProcessingTabUiConfig
    _placeholder_name = "Постобработка"

    def _build_panel_kwargs(self) -> dict[str, Any]:
        """Прокинуть action_bus из tab kwargs в панель."""
        kw: dict[str, Any] = {}
        ab = self._extra_kwargs.get("action_bus")
        if ab is not None:
            kw["action_bus"] = ab
        return kw
