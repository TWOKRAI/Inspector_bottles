# multiprocess_prototype/frontend/widgets/hikvision_widget/presenter.py
"""Презентер Hikvision: логика устройства, grabbing, параметров."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from frontend_module.components.tabs import TabPresenterBase
from frontend_module.interfaces import IRegistersManagerGui

from .register_ops import (
    apply_hikvision_params_dict,
    read_hikvision_triple_from_register,
)
from .schemas import HikvisionUiConfig

if TYPE_CHECKING:
    from .callbacks import HikvisionWidgetCallbacks
    from .view import HikvisionView


class HikvisionPresenter(TabPresenterBase["HikvisionView", HikvisionUiConfig]):
    """Логика Hikvision: open, start_grabbing, set_parameters."""

    def __init__(
        self,
        *,
        view: "HikvisionView",
        rm: Optional[IRegistersManagerGui],
        ui: HikvisionUiConfig,
        callbacks: "HikvisionWidgetCallbacks",
    ):
        super().__init__(view=view, rm=rm, ui=ui)
        self._callbacks = callbacks

    def on_open(self) -> None:
        cb = self._callbacks.on_open
        if cb:
            cb(camera_index=self._view.get_selected_camera_index())

    def on_start_grabbing(self) -> None:
        if self._callbacks.on_open:
            self._callbacks.on_open(camera_index=self._view.get_selected_camera_index())
        if self._callbacks.on_start_grabbing:
            self._callbacks.on_start_grabbing()

    def on_set_parameters_clicked(self) -> None:
        if self._rm is not None:
            fr, exp, gain = read_hikvision_triple_from_register(self._rm, self._ui)
        else:
            fr, exp, gain = self._view.get_hikvision_params_from_lines()
        if self._callbacks.on_set_parameters:
            self._callbacks.on_set_parameters(fr, exp, gain)

    def update_camera_devices(self, devices: list) -> None:
        self._view.set_devices_list(devices or [])

    def update_camera_parameters(self, params: dict[str, Any]) -> None:
        if not params:
            return
        apply_hikvision_params_dict(self._rm, params, self._ui)
        self._view.set_hikvision_params_lines(params)
