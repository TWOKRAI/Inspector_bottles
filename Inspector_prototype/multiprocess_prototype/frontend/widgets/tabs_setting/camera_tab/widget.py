# multiprocess_prototype/frontend/widgets/camera_tab/widget.py
"""
CameraTabWidget — контейнер: ComboBox типа камеры + StackedWidget с тремя виджетами.

Дочерние виджеты: SimWebcamWidget (simulator / webcam) и HikvisionCameraMvpWidget.
Нужны ``command_handler`` (для Hikvision MVP) и ``callbacks_map`` для Sim/Webcam и on_camera_type_changed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from frontend_module.widgets.tabs import BaseTab
from frontend_module.core.qt_imports import QComboBox, QGroupBox, QStackedWidget, QVBoxLayout
from frontend_module.core.schema_config import coerce_schema_config

from multiprocess_prototype.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts

from ...hikvision_camera_mvp import HikvisionCameraMvpWidget
from ...camera_common import SimWebcamWidget

from .presenter import CameraTabPresenter
from .schemas import CameraTabUiConfig


class CameraTabWidget(BaseTab):
    """Вкладка камеры: переключатель Simulator/Webcam/Hikvision и три виджета."""

    def __init__(
        self,
        *,
        camera_type: str = "simulator",
        registers_manager: Optional[Any] = None,
        callbacks_map: Optional[Dict[str, Any]] = None,
        command_handler: Optional[Any] = None,
        ui: Optional[Union[CameraTabUiConfig, dict]] = None,
        touch_keyboard: Any | None = None,
        parent: Optional[Any] = None,
    ):
        """ComboBox типа камеры + стек из SimWebcam×2 и Hikvision MVP."""
        super().__init__(parent)
        self._registers_manager = registers_manager
        self._callbacks_map = callbacks_map or {}
        self._command_handler = command_handler
        self._ui = coerce_schema_config(ui, CameraTabUiConfig)
        self._touch_keyboard = merge_touch_keyboard_dicts(
            touch_keyboard, getattr(self._ui, "touch_keyboard", None)
        )
        self._camera_type_map = self._ui.camera_type_index_map()
        self._presenter = CameraTabPresenter(
            view=self,
            rm=registers_manager,
            ui=self._ui,
            callbacks_map=self._callbacks_map,
        )
        self._init_ui()

        idx = self._camera_type_map.get(camera_type, 0)
        self._presenter.apply_initial_camera_type(camera_type, stack_index=idx)

    def _init_ui(self) -> None:
        """Верх: выбор типа камеры; низ: QStackedWidget с тремя страницами."""
        u = self._ui
        root = QVBoxLayout(self)

        # --- Блок: тип камеры (ComboBox) ---
        type_group = QGroupBox(u.group_camera_type)
        type_layout = QVBoxLayout(type_group)
        self._combo_camera_type = QComboBox()
        self._combo_camera_type.addItems(list(u.camera_type_options))
        self._combo_camera_type.setMinimumWidth(u.camera_type_combo_min_width)
        self._combo_camera_type.currentIndexChanged.connect(self._presenter.on_camera_type_changed)
        type_layout.addWidget(self._combo_camera_type)
        root.addWidget(type_group)

        # --- Блок: три виджета (simulator, webcam, hikvision) в стеке ---
        self._stack = QStackedWidget()
        tk_fps = merge_touch_keyboard_dicts(self._touch_keyboard, getattr(u, "touch_keyboard_fps", None))
        tk_hik = merge_touch_keyboard_dicts(self._touch_keyboard, getattr(u, "touch_keyboard_hikvision", None))
        sim = SimWebcamWidget(
            camera_type_id="simulator",
            registers_manager=self._registers_manager,
            callbacks=self._callbacks_map.get("simulator"),
            touch_keyboard=tk_fps,
        )
        web = SimWebcamWidget(
            camera_type_id="webcam",
            registers_manager=self._registers_manager,
            callbacks=self._callbacks_map.get("webcam"),
            touch_keyboard=tk_fps,
        )
        if self._command_handler is None:
            raise TypeError("CameraTabWidget requires command_handler for HikvisionCameraMvpWidget")
        hik = HikvisionCameraMvpWidget(
            registers_manager=self._registers_manager,
            command_handler=self._command_handler,
            ui=self._ui.hikvision,
            touch_keyboard=tk_hik,
            webcam_enum_max_index=self._ui.webcam_enum_max_index,
        )
        self._stack.addWidget(sim)
        self._stack.addWidget(web)
        self._stack.addWidget(hik)
        self._hik_widget = hik

        root.addWidget(self._stack)

    def set_stack_index(self, index: int) -> None:
        """Показать страницу стека по индексу."""
        self._stack.setCurrentIndex(index)

    def set_combo_index(self, index: int, *, block_signals: bool = False) -> None:
        """Синхронизировать ComboBox с регистром/стеком (опционально без currentIndexChanged)."""
        if block_signals:
            self._combo_camera_type.blockSignals(True)
        self._combo_camera_type.setCurrentIndex(index)
        if block_signals:
            self._combo_camera_type.blockSignals(False)

    def sync_camera_type(self, camera_type: str) -> None:
        """Выставить combo и стек по строковому id типа камеры."""
        idx = self._camera_type_map.get(camera_type, 0)
        self.set_combo_index(idx, block_signals=True)
        self.set_stack_index(idx)

    def update_camera_devices(self, devices: list) -> None:
        """Проброс списка устройств в HikvisionWidget (IPC / enum)."""
        self._hik_widget.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        """Проброс параметров камеры в HikvisionWidget."""
        self._hik_widget.update_camera_parameters(params)

    @property
    def registers_manager(self):
        """Rm вкладки (для внешнего кода)."""
        return self._registers_manager
