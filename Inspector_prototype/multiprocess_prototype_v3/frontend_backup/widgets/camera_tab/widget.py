"""CameraTabWidget — camera type selector with stacked pages."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from frontend_module.core.qt_imports import (
    QComboBox, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from multiprocess_prototype_v3.registers.camera import (
    CAMERA_TYPE_LABELS, CAMERA_TYPES,
)


class CameraTabWidget(QWidget):
    """Camera type selector with Simulator/Webcam/Hikvision pages."""

    def __init__(
        self,
        camera_type: str = "simulator",
        registers_manager: Any = None,
        callbacks_map: Optional[Dict[str, Callable]] = None,
        command_handler: Any = None,
        ui: Any = None,
        touch_keyboard: Any = None,
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self._rm = registers_manager
        self._callbacks = callbacks_map or {}
        self._cmd = command_handler
        self._camera_type = camera_type
        self._init_ui()
        self._sync_initial_camera_type()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Camera type selector
        type_group = QGroupBox("Тип камеры")
        type_layout = QHBoxLayout(type_group)
        self._type_combo = QComboBox()
        self._type_combo.addItems(list(CAMERA_TYPE_LABELS))
        self._type_combo.setMinimumWidth(180)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(QLabel("Камера:"))
        type_layout.addWidget(self._type_combo)
        type_layout.addStretch()
        layout.addWidget(type_group)

        # Stacked pages
        self._stack = QStackedWidget()
        self._stack.addWidget(self._create_sim_webcam_page("simulator"))
        self._stack.addWidget(self._create_sim_webcam_page("webcam"))
        self._stack.addWidget(self._create_hikvision_page())
        layout.addWidget(self._stack)
        layout.addStretch()

    def _create_sim_webcam_page(self, camera_type_id: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        ctrl = QGroupBox("Управление")
        cl = QHBoxLayout(ctrl)

        btn_start = QPushButton("Start")
        btn_stop = QPushButton("Stop")
        fps_spin = QSpinBox()
        fps_spin.setRange(1, 120)
        fps_spin.setValue(25)
        fps_spin.setSuffix(" fps")

        btn_start.clicked.connect(lambda: self._callbacks.get("start_capture", lambda: None)())
        btn_stop.clicked.connect(lambda: self._callbacks.get("stop_capture", lambda: None)())
        fps_spin.valueChanged.connect(lambda v: self._callbacks.get("set_fps", lambda x: None)(v))

        cl.addWidget(btn_start)
        cl.addWidget(btn_stop)
        cl.addWidget(QLabel("FPS:"))
        cl.addWidget(fps_spin)
        cl.addStretch()
        lay.addWidget(ctrl)
        lay.addStretch()
        return page

    def _create_hikvision_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)

        ctrl = QGroupBox("Подключение")
        cl = QHBoxLayout(ctrl)
        btn_enum = QPushButton("Поиск устройств")
        btn_open = QPushButton("Открыть")
        btn_close = QPushButton("Закрыть")
        btn_start = QPushButton("Старт")
        btn_stop = QPushButton("Стоп")

        btn_enum.clicked.connect(lambda: self._callbacks.get("enum_devices", lambda: None)())
        btn_open.clicked.connect(lambda: self._callbacks.get("open_camera", lambda x: None)(0))
        btn_close.clicked.connect(lambda: self._callbacks.get("close_camera", lambda: None)())
        btn_start.clicked.connect(lambda: self._callbacks.get("start_grabbing", lambda: None)())
        btn_stop.clicked.connect(lambda: self._callbacks.get("stop_grabbing", lambda: None)())

        cl.addWidget(btn_enum)
        cl.addWidget(btn_open)
        cl.addWidget(btn_close)
        cl.addWidget(btn_start)
        cl.addWidget(btn_stop)
        lay.addWidget(ctrl)

        self._device_list_label = QLabel("Устройства: не найдены")
        lay.addWidget(self._device_list_label)
        self._params_label = QLabel("Параметры: —")
        lay.addWidget(self._params_label)
        lay.addStretch()
        return page

    def _on_type_changed(self, index: int):
        if 0 <= index < len(CAMERA_TYPES):
            camera_type = CAMERA_TYPES[index]
            self._camera_type = camera_type
            self._stack.setCurrentIndex(index)
            cb = self._callbacks.get("set_camera_type")
            if cb:
                cb(camera_type)

    def _sync_initial_camera_type(self):
        try:
            idx = CAMERA_TYPES.index(self._camera_type)
        except ValueError:
            idx = 0
        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentIndex(idx)
        self._stack.setCurrentIndex(idx)
        self._type_combo.blockSignals(False)

    # --- Public API ---

    def sync_camera_type(self, camera_type: str):
        self._camera_type = camera_type
        self._sync_initial_camera_type()

    def update_camera_devices(self, devices: list):
        text = "Устройства: " + ", ".join(str(d) for d in devices) if devices else "Устройства: не найдены"
        self._device_list_label.setText(text)

    def update_camera_parameters(self, params: dict):
        if params:
            self._params_label.setText("Параметры: " + ", ".join(f"{k}={v}" for k, v in params.items()))
        else:
            self._params_label.setText("Параметры: —")
