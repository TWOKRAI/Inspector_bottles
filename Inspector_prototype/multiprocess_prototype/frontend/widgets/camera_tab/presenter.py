# multiprocess_prototype/frontend/widgets/camera_tab/presenter.py
"""
Презентер вкладки камеры: логика без Qt.

Порядок в обработчиках (TAB_STRUCTURE): регистр → колбэк → вью.
Хранит _camera_type и _camera_type_map для sync_camera_type при внешних update_*.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from frontend_module.components.tabs import TabPresenterBase
from frontend_module.interfaces import IRegistersManagerGui

from .register_ops import (
    apply_hikvision_params_dict,
    persist_camera_type,
    read_hikvision_triple_from_register,
    set_camera_type_field,
)

if TYPE_CHECKING:
    from .callbacks import CameraTabCallbacks
    from .schemas import CameraTabUiConfig
    from .view import CameraTabView


class CameraTabPresenter(TabPresenterBase["CameraTabView", "CameraTabUiConfig"]):
    """Бизнес-логика: регистр, колбэки, координация с вью."""

    def __init__(
        self,
        *,
        view: "CameraTabView",
        callbacks: "CameraTabCallbacks",
        rm: Optional[IRegistersManagerGui],
        ui: "CameraTabUiConfig",
    ):
        super().__init__(view=view, rm=rm, ui=ui)
        self._callbacks = callbacks
        self._camera_type = "simulator"
        self._camera_type_map = ui.camera_type_index_map()

    def on_camera_type_changed(self, combo_index: int) -> None:
        """Записать в регистр, persist, переключить страницу стека (0=Sim, 1=Hikvision)."""
        self._camera_type = self._ui.camera_type_for_combo_index(combo_index)
        set_camera_type_field(self._rm, self._camera_type)
        if self._rm is not None:
            persist_camera_type(self._camera_type)
        else:
            cb = self._callbacks.on_camera_type_changed
            if cb:
                cb(self._camera_type)
        stack_idx = 1 if self._camera_type == self._ui.camera_type_id_for_hikvision_page else 0
        self._view.set_stack_index(stack_idx)

    def on_fps_changed(self, value: int) -> None:
        self._view.set_fps_label_text(f"{value}{self._ui.fps_suffix}")
        cb = self._callbacks.on_set_fps
        if cb:
            cb(value)

    def on_hikvision_open(self) -> None:
        cb = self._callbacks.on_open
        if cb:
            cb(camera_index=self._view.get_selected_camera_index())

    def on_hikvision_start_grabbing(self) -> None:
        """Open (если нет rm) + Start Grabbing — два шага для Hikvision API."""
        if self._callbacks.on_open:
            self._callbacks.on_open(camera_index=self._view.get_selected_camera_index())
        if self._callbacks.on_start_grabbing:
            self._callbacks.on_start_grabbing()

    def on_hikvision_set_parameters_clicked(self) -> None:
        """Читает triple, вызывает on_set_parameters (фаза 2.5: регистр/вью → колбэк)."""
        if self._rm is not None:
            fr, exp, gain = read_hikvision_triple_from_register(self._rm, self._ui)
        else:
            fr, exp, gain = self._view.get_hikvision_params_from_lines()
        cb = self._callbacks.on_set_parameters
        if cb:
            cb(fr, exp, gain)

    def sync_camera_type(self, camera_type: str) -> None:
        self._camera_type = camera_type
        idx = self._camera_type_map.get(camera_type, 0)
        self._view.set_camera_type_combo_index(idx)
        stack_idx = 1 if camera_type == self._ui.camera_type_id_for_hikvision_page else 0
        self._view.set_stack_index(stack_idx)

    def update_camera_devices(self, devices: list) -> None:
        self._view.set_devices_list(devices or [])

    def update_camera_parameters(self, params: dict[str, Any]) -> None:
        if not params:
            return
        apply_hikvision_params_dict(self._rm, params, self._ui)
        self._view.set_hikvision_params_lines(params)
