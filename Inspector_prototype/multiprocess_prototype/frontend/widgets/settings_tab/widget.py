# multiprocess_prototype/frontend/widgets/settings_tab/widget.py
"""
SettingsTabWidget — вкладка настроек.

NumericControl, CheckboxControl по конфигу (control_v2 API).

Доступность контролов: RegisterBindingContext + IRegistersManagerGui; при
отсутствии rm — заглушка (см. TAB_STRUCTURE.md).
"""

from __future__ import annotations

from typing import Any, Optional, Union

from frontend_module.components import BaseTab
from frontend_module.components.tabs import RegisterBindingContext, create_registers_placeholder
from frontend_module.components.control_v2 import (
    BindingConfig,
    CheckboxControl,
    CheckboxViewConfig,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.core.qt_imports import QGroupBox, QVBoxLayout, QWidget
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.interfaces import IRegistersManagerGui

from .schemas import SettingsTabConfig


class SettingsTabWidget(BaseTab):
    """Вкладка настроек: слайдеры и чекбоксы по конфигу."""

    def __init__(
        self,
        *,
        registers_manager: Optional[IRegistersManagerGui] = None,
        ui: Optional[Union[SettingsTabConfig, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._config = coerce_schema_config(ui, SettingsTabConfig)
        self._init_ui()

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        return self._registers_manager

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        binding = RegisterBindingContext(rm=self._registers_manager)

        if not binding.can_bind:
            layout.addWidget(create_registers_placeholder("Настройки"))
            layout.addStretch()
            return

        rm = binding.rm
        assert rm is not None

        group = QGroupBox(self._config.group_title)
        group_layout = QVBoxLayout(group)
        for ctrl in self._config.controls:
            w = self._create_control(rm, ctrl.to_control_dict())
            if w:
                group_layout.addWidget(w)
        layout.addWidget(group)
        layout.addStretch()

    def _create_control(self, rm: IRegistersManagerGui, cfg: dict) -> Optional[Any]:
        """
        Создаёт NumericControl (slider) или CheckboxControl по cfg.

        cfg: type, register_name, field_name, component_config (label, position).
        """
        ctype = cfg.get("type", "slider")
        reg = cfg.get("register_name")
        field = cfg.get("field_name")
        component_config = dict(cfg.get("component_config") or {})
        if not reg or not field:
            return None
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
