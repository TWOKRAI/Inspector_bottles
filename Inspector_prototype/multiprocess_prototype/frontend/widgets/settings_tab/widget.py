# multiprocess_prototype/frontend/widgets/settings_tab/widget.py
"""
SettingsTabWidget — вкладка настроек.

NumericControl, CheckboxControl по конфигу (control_v2 API).
"""

from typing import Any, List, Optional

from frontend_module.components import BaseTab
from frontend_module.components.controls import (
    BindingConfig,
    CheckboxControl,
    CheckboxViewConfig,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.core.qt_imports import QGroupBox, QVBoxLayout, QWidget

from .config import SettingsTabConfig


class SettingsTabWidget(BaseTab):
    """Вкладка настроек: слайдеры и чекбоксы по конфигу."""

    def __init__(
        self,
        *,
        registers_manager: Optional[Any] = None,
        controls_config: Optional[List[dict]] = None,
        group_title: str = "Параметры отображения",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._controls_config = controls_config or SettingsTabConfig().to_controls_dict_list()
        self._group_title = group_title
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        group = QGroupBox(self._group_title)
        group_layout = QVBoxLayout(group)
        for cfg in self._controls_config:
            w = self._create_control(cfg)
            if w:
                group_layout.addWidget(w)
        layout.addWidget(group)
        layout.addStretch()

    def _create_control(self, cfg: dict) -> Optional[Any]:
        ctype = cfg.get("type", "slider")
        reg = cfg.get("register_name")
        field = cfg.get("field_name")
        component_config = dict(cfg.get("component_config") or {})
        if not reg or not field:
            return None
        rm = self._registers_manager
        binding = BindingConfig(reg, field)
        if ctype == "slider":
            view_cfg = NumericViewConfig(
                view_type="slider",
                label=component_config.get("label"),
            )
            result = NumericControl.create(rm, binding, view_cfg)
            return result.widget
        if ctype == "checkbox":
            view_cfg = CheckboxViewConfig(
                position=component_config.get("position", "left"),
                label=component_config.get("label"),
            )
            result = CheckboxControl.create(rm, binding, view_cfg)
            return result.widget
        return None
