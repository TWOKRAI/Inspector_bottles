# multiprocess_prototype_v3/frontend/widgets/camera_tab/presenter.py
"""Презентер вкладки камеры: тип камеры в регистрах, колбэк в capture, обновление стека."""

from __future__ import annotations

from typing import Any, Dict, Optional

from frontend_module.interfaces import IRegistersManagerGui
from frontend_module.widgets.tabs import TabPresenterBase

from multiprocess_prototype_v3.frontend.coordinators.logical_cameras import (
    ensure_logical_camera_and_seed_roi,
)

from .register_ops import persist_camera_type, set_camera_type_field
from .schemas import CameraTabUiConfig
from .view import CameraTabView


class CameraTabPresenter(TabPresenterBase[CameraTabView, CameraTabUiConfig]):
    def __init__(
        self,
        *,
        view: CameraTabView,
        rm: Optional[IRegistersManagerGui],
        ui: CameraTabUiConfig,
        callbacks_map: Dict[str, Any],
    ) -> None:
        """callbacks_map — колбэки дочерних виджетов + on_camera_type_changed для IPC."""
        super().__init__(view=view, rm=rm, ui=ui)
        self._callbacks_map = callbacks_map

    def on_camera_type_changed(self, index: int) -> None:
        """Запись camera_type в регистр и диск, команда воркеру, смена страницы стека."""
        camera_type = self._ui.camera_type_for_combo_index(index)
        set_camera_type_field(self._rm, camera_type)
        ensure_logical_camera_and_seed_roi(self._rm)
        persist_camera_type(camera_type)
        # Явная команда — register_update обрабатывается только в capture_worker,
        # который при остановленном захвате не читает очередь.
        cb = self._callbacks_map.get("on_camera_type_changed")
        if cb:
            cb(camera_type)
        self._view.set_stack_index(index)

    def apply_initial_camera_type(self, camera_type: str, stack_index: int) -> None:
        """При старте: записать тип в rm/диск и выставить combo+стек без сигнала."""
        if self._rm is not None:
            set_camera_type_field(self._rm, camera_type)
            ensure_logical_camera_and_seed_roi(self._rm)
            persist_camera_type(camera_type)
        self._view.set_combo_index(stack_index, block_signals=True)
        self._view.set_stack_index(stack_index)
