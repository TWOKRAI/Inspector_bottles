# multiprocess_prototype/frontend/widgets/cropped_regions_tab/widget.py
"""Вкладка ROI: оболочка — placeholder или CroppedRegionsPanelWidget."""

from __future__ import annotations

from typing import Any, Optional, Union

from frontend_module.core.qt_imports import QVBoxLayout, QWidget
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui
from frontend_module.widgets.tabs import BaseTab, RegisterBindingContext, create_registers_placeholder

from multiprocess_prototype_v2.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts

from ...cropped_regions_widget import CroppedRegionsPanelWidget
from ...cropped_regions_widget.schemas import CroppedRegionsTabUiConfig


class CroppedRegionsTabWidget(BaseTab):
    """Тонкая вкладка: RegisterBindingContext + фиче-виджет BaseWidget."""

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[CroppedRegionsTabUiConfig, dict]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        """CroppedRegionsPanelWidget или заглушка."""
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._u = coerce_schema_config(ui, CroppedRegionsTabUiConfig)
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard, getattr(self._u, "touch_keyboard", None)
        )
        self._panel: Optional[CroppedRegionsPanelWidget] = None
        self._init_ui()

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        """Rm вкладки."""
        return self._registers_manager

    def _init_ui(self) -> None:
        """Placeholder или панель ROI (таблица + слайдеры)."""
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Области (ROI)"))
            layout.addStretch()
            return

        rm = binding.rm
        assert rm is not None

        # --- Полная панель регионов обрезки ---
        self._panel = CroppedRegionsPanelWidget(
            registers_manager=rm,
            ui=self._u,
            touch_keyboard=self._touch_keyboard,
            parent=self,
        )
        layout.addWidget(self._panel, 1)
