# multiprocess_prototype/frontend/widgets/tabs_setting/camera_tab/widget.py
"""
CameraTabWidget — контейнер: ComboBox типа камеры + StackedWidget с тремя виджетами.

Дочерние виджеты: SimWebcamWidget (simulator / webcam) и HikvisionWidget.
callbacks_map: {"simulator": SimWebcamWidgetCallbacks, "webcam": ..., "hikvision": ...}.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from frontend_module.components import BaseTab
from frontend_module.core.qt_imports import QComboBox, QGroupBox, QStackedWidget, QVBoxLayout
from frontend_module.core.schema_config import coerce_schema_config

from ...hikvision_widget import HikvisionWidget
from ...camera_common import SimWebcamWidget

from .register_ops import persist_camera_type, set_camera_type_field
from .schemas import CameraTabUiConfig


class CameraTabWidget(BaseTab):
    """Вкладка камеры: переключатель Simulator/Webcam/Hikvision и три виджета."""

    def __init__(
        self,
        *,
        camera_type: str = "simulator",
        registers_manager: Optional[Any] = None,
        callbacks_map: Optional[Dict[str, Any]] = None,
        ui: Optional[Union[CameraTabUiConfig, dict]] = None,
        parent: Optional[Any] = None,
    ):
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._callbacks_map = callbacks_map or {}
        self._ui = coerce_schema_config(ui, CameraTabUiConfig)
        self._camera_type_map = self._ui.camera_type_index_map()
        self._init_ui()

        idx = self._camera_type_map.get(camera_type, 0)
        self._combo_camera_type.setCurrentIndex(idx)
        self._stack.setCurrentIndex(idx)
        if registers_manager:
            set_camera_type_field(registers_manager, camera_type)
            persist_camera_type(camera_type)

    def _init_ui(self) -> None:
        u = self._ui
        root = QVBoxLayout(self)

        type_group = QGroupBox(u.group_camera_type)
        type_layout = QVBoxLayout(type_group)
        self._combo_camera_type = QComboBox()
        self._combo_camera_type.addItems(list(u.camera_type_options))
        self._combo_camera_type.setMinimumWidth(u.camera_type_combo_min_width)
        self._combo_camera_type.currentIndexChanged.connect(self._on_camera_type_changed)
        type_layout.addWidget(self._combo_camera_type)
        root.addWidget(type_group)

        self._stack = QStackedWidget()
        sim = SimWebcamWidget(
            camera_type_id="simulator",
            registers_manager=self._registers_manager,
            callbacks=self._callbacks_map.get("simulator"),
        )
        web = SimWebcamWidget(
            camera_type_id="webcam",
            registers_manager=self._registers_manager,
            callbacks=self._callbacks_map.get("webcam"),
        )
        hik = HikvisionWidget(
            registers_manager=self._registers_manager,
            callbacks=self._callbacks_map.get("hikvision"),
            ui=self._ui.hikvision,
        )
        self._stack.addWidget(sim)
        self._stack.addWidget(web)
        self._stack.addWidget(hik)
        self._hik_widget = hik

        root.addWidget(self._stack)

    def _on_camera_type_changed(self, index: int) -> None:
        camera_type = self._ui.camera_type_for_combo_index(index)
        set_camera_type_field(self._registers_manager, camera_type)
        persist_camera_type(camera_type)
        # Явная команда — register_update обрабатывается только в capture_worker,
        # который при остановленном захвате не читает очередь.
        cb = self._callbacks_map.get("on_camera_type_changed")
        if cb:
            cb(camera_type)
        self._stack.setCurrentIndex(index)

    def sync_camera_type(self, camera_type: str) -> None:
        idx = self._camera_type_map.get(camera_type, 0)
        self._combo_camera_type.blockSignals(True)
        self._combo_camera_type.setCurrentIndex(idx)
        self._combo_camera_type.blockSignals(False)
        self._stack.setCurrentIndex(idx)

    def update_camera_devices(self, devices: list) -> None:
        self._hik_widget.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        self._hik_widget.update_camera_parameters(params)

    @property
    def registers_manager(self):
        return self._registers_manager
