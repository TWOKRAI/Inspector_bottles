# multiprocess_prototype/frontend/widgets/hikvision_widget/widget.py
"""HikvisionWidget — виджет управления камерой Hikvision."""

from __future__ import annotations

from typing import Optional, Union

from frontend_module.components import BaseTab
from frontend_module.components.tabs import RegisterBindingContext
from frontend_module.core.qt_imports import QVBoxLayout
from frontend_module.core.schema_config import coerce_schema_config

from .binder import bind_hikvision_ui
from .callbacks import HikvisionWidgetCallbacks
from .presenter import HikvisionPresenter
from .schemas import HikvisionUiConfig


class HikvisionWidget(BaseTab):
    """Виджет Hikvision: устройство, Open/Close, Grabbing, параметры."""

    def __init__(
        self,
        *,
        registers_manager=None,
        callbacks: Optional[HikvisionWidgetCallbacks] = None,
        ui: Optional[Union[HikvisionUiConfig, dict]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._callbacks = callbacks or HikvisionWidgetCallbacks()
        self._ui = coerce_schema_config(ui, HikvisionUiConfig)
        self._devices: list = []
        self._refs = None

        binding = RegisterBindingContext(rm=self._registers_manager)
        self._presenter = HikvisionPresenter(
            view=self,
            rm=self._registers_manager,
            ui=self._ui,
            callbacks=self._callbacks,
        )
        self._page, self._refs = bind_hikvision_ui(
            self._ui, binding, self._callbacks, self._presenter
        )
        root = QVBoxLayout(self)
        root.addWidget(self._page)

    def get_selected_camera_index(self) -> int:
        if not self._refs:
            return 0
        idx = self._refs.combo_devices.currentIndex()
        if idx <= 0 or idx > len(self._devices):
            return 0
        return self._devices[idx - 1].get("index", 0)

    def set_devices_list(self, devices: list) -> None:
        self._devices = devices or []
        if not self._refs:
            return
        combo = self._refs.combo_devices
        combo.clear()
        combo.addItem(self._ui.device_combo_placeholder)
        for dev in self._devices:
            display = dev.get("display_name", f"[{dev.get('index', '?')}]")
            combo.addItem(display)

    def set_hikvision_params_lines(self, params: dict) -> None:
        if not self._refs:
            return
        for m, ed in zip(self._ui.hikvision_api_to_register, self._refs.hik_params.line_edits):
            if ed is None:
                continue
            raw = float(params.get(m.api_key, 0))
            ed.setText(format(raw, m.line_edit_format_spec))

    def get_hikvision_params_from_lines(self) -> tuple[float, float, float]:
        hp = self._refs.hik_params if self._refs else None
        if not hp or not hp.line_edits:
            return (25.0, 10000.0, 0.0)
        try:
            vals = []
            for m, ed in zip(self._ui.hikvision_api_to_register, hp.line_edits):
                if ed is None:
                    return (25.0, 10000.0, 0.0)
                vals.append(float(ed.text() or m.parse_empty_default))
            return (vals[0], vals[1], vals[2])
        except (ValueError, IndexError):
            return (25.0, 10000.0, 0.0)

    def update_camera_devices(self, devices: list) -> None:
        self._presenter.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        self._presenter.update_camera_parameters(params)

    @property
    def registers_manager(self):
        return self._registers_manager
