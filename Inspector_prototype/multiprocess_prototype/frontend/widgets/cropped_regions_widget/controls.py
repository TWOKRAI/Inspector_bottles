# multiprocess_prototype/frontend/widgets/cropped_regions_widget/controls.py
"""Панель ROI: NumericControl (slider/spinbox) и локальный RegistersManager + data_schema."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Literal, Optional, Union

from frontend_module.components import (
    BindingConfig,
    ControlHooks,
    ControlWriteCommittedEvent,
    NumericControl,
    NumericViewConfig,
)
from frontend_module.components.base.touch_keyboard_config import coerce_touch_keyboard
from frontend_module.core.qt_imports import QGroupBox, QVBoxLayout, QWidget
from frontend_module.core.schema_config import coerce_schema_config

from registers_module import RegistersManager

from .params import CROPPED_PARAM_KEYS
from .roi_panel_registers import (
    CROPPED_ROI_PANEL_REGISTER,
    CroppedRoiPanelRegisters,
    NUMERIC_ROI_FIELD_NAMES,
)
from .schemas import CroppedRegionsTabUiConfig


class CroppedAreaControls(QWidget):
    """Четыре числовых поля x, y, width, height через NumericControl."""

    def __init__(
        self,
        *,
        on_changed: Optional[Callable[[], None]] = None,
        ui: Optional[Union[CroppedRegionsTabUiConfig, dict]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_changed = on_changed
        self._ui = coerce_schema_config(ui, CroppedRegionsTabUiConfig)
        self._touch_keyboard = touch_keyboard
        self._suppress_emit = False
        self._rm = RegistersManager(
            registers={CROPPED_ROI_PANEL_REGISTER: CroppedRoiPanelRegisters()}
        )
        self._hooks = ControlHooks(on_write_committed=self._on_write_committed)
        self._numeric_results: List[Any] = []
        self._init_ui()

    def _on_write_committed(self, _event: ControlWriteCommittedEvent) -> None:
        if self._suppress_emit:
            return
        if self._on_changed:
            self._on_changed()

    def _numeric_view_type(self, field_name: str) -> Literal["slider", "spinbox"]:
        raw = (self._ui.roi_numeric_views or {}).get(field_name, "slider")
        if str(raw).lower() == "spinbox":
            return "spinbox"
        return "slider"

    def _numeric_view_config(self, field_name: str) -> NumericViewConfig:
        meta = CroppedRoiPanelRegisters.get_field_meta(field_name)
        label = (meta.description if meta and meta.description else None) or field_name
        min_v = float(meta.min) if meta and meta.min is not None else None
        max_v = float(meta.max) if meta and meta.max is not None else None
        return NumericViewConfig(
            view_type=self._numeric_view_type(field_name),
            label=label,
            min_val=min_v,
            max_val=max_v,
            label_position="left",
            touch_keyboard=coerce_touch_keyboard(self._touch_keyboard),
        )

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        group = QGroupBox(self._ui.group_roi_params)
        col = QVBoxLayout(group)

        for name in NUMERIC_ROI_FIELD_NAMES:
            vc = self._numeric_view_config(name)
            res = NumericControl.create(
                self._rm,
                BindingConfig(CROPPED_ROI_PANEL_REGISTER, name),
                view_config=vc,
                hooks=self._hooks,
            )
            self._numeric_results.append(res)
            col.addWidget(res.widget)

        root.addWidget(group)

    def get_params(self) -> Dict[str, Any]:
        reg = self._rm.get_register(CROPPED_ROI_PANEL_REGISTER)
        if reg is None or not hasattr(reg, "model_dump"):
            return {}
        data = reg.model_dump()
        return {k: data[k] for k in CROPPED_PARAM_KEYS if k in data}

    def apply_params(self, params_dict: Optional[Dict[str, Any]]) -> None:
        if not params_dict:
            return
        self._suppress_emit = True
        try:
            for key in CROPPED_PARAM_KEYS:
                if key not in params_dict:
                    continue
                val = params_dict[key]
                try:
                    val = int(round(float(val)))
                except (TypeError, ValueError):
                    continue
                self._rm.set_field_value(CROPPED_ROI_PANEL_REGISTER, key, val)
        finally:
            self._suppress_emit = False
