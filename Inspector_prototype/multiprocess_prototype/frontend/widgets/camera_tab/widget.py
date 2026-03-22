# multiprocess_prototype/frontend/widgets/camera_tab/widget.py
"""
CameraTabWidget — вкладка управления камерой.

При наличии registers_manager: camera_type и fps идут через set_field_value → register_update.
Иначе callbacks (legacy).
"""

from typing import Any, Callable, Dict, Optional, Union

from frontend_module.components import BaseTab, SliderConfig, SliderControl
from frontend_module.core.qt_imports import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    Qt,
)

from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER

from .ui_config import CameraTabUiConfig


def _coerce_camera_ui(ui: Optional[Union[CameraTabUiConfig, dict]]) -> CameraTabUiConfig:
    if ui is None:
        return CameraTabUiConfig()
    if isinstance(ui, CameraTabUiConfig):
        return ui
    return CameraTabUiConfig.model_validate(ui)


class CameraTabWidget(BaseTab):
    """
    Вкладка камеры: Simulator/Webcam/Hikvision, Start/Stop, FPS, Hikvision-панель.

    При registers_manager: camera_type и fps через set_field_value.
    Callbacks: on_start, on_stop, on_enum_devices, on_open, on_close,
    on_start_grabbing, on_stop_grabbing, on_get_parameters, on_set_parameters.
    """

    def __init__(
        self,
        *,
        camera_type: str = "simulator",
        registers_manager: Optional[Any] = None,
        callbacks: Optional[Dict[str, Callable]] = None,
        ui: Optional[Union[CameraTabUiConfig, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._camera_type = camera_type
        self._registers_manager = registers_manager
        self._callbacks = dict(callbacks) if callbacks else {}
        self._hikvision_devices: list = []
        self._u = _coerce_camera_ui(ui)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        type_group = QGroupBox(self._u.group_camera_type)
        type_layout = QVBoxLayout(type_group)
        self._combo_camera_type = QComboBox()
        self._combo_camera_type.addItems(list(self._u.camera_type_options))
        self._camera_type_map = {"simulator": 0, "webcam": 1, "hikvision": 2}
        self._combo_camera_type.setMinimumWidth(180)
        self._combo_camera_type.setCurrentIndex(
            self._camera_type_map.get(self._camera_type, 0)
        )
        self._combo_camera_type.currentIndexChanged.connect(self._on_camera_type_changed)
        type_layout.addWidget(self._combo_camera_type)
        layout.addWidget(type_group)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_sim_webcam_page())
        self._stack.addWidget(self._build_hikvision_page())
        self._stack.setCurrentIndex(1 if self._camera_type == "hikvision" else 0)
        layout.addWidget(self._stack)

        layout.addStretch()

    def _build_sim_webcam_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        btn_group = QGroupBox(self._u.group_sim_control)
        btn_layout = QVBoxLayout(btn_group)
        self._btn_start = QPushButton(self._u.btn_start)
        self._btn_start.clicked.connect(self._cb("on_start"))
        self._btn_stop = QPushButton(self._u.btn_stop)
        self._btn_stop.clicked.connect(self._cb("on_stop"))
        btn_layout.addWidget(self._btn_start)
        btn_layout.addWidget(self._btn_stop)
        layout.addWidget(btn_group)
        fps_group = QGroupBox(self._u.group_fps)
        fps_layout = QVBoxLayout(fps_group)
        rm = self._registers_manager
        if rm and hasattr(rm, "set_field_value"):
            fps_layout.addWidget(
                SliderControl(
                    config=SliderConfig(
                        register_name=CAMERA_REGISTER,
                        field_name="fps",
                        label="FPS",
                    ),
                    registers_manager=rm,
                    parent=self,
                )
            )
        else:
            self._fps_label = QLabel(f"{self._u.initial_fps}{self._u.fps_suffix}")
            self._fps_slider = QSlider(Qt.Horizontal)
            self._fps_slider.setRange(1, 60)
            self._fps_slider.setValue(self._u.initial_fps)
            self._fps_slider.valueChanged.connect(self._on_fps_changed)
            fps_layout.addWidget(self._fps_label)
            fps_layout.addWidget(self._fps_slider)
        layout.addWidget(fps_group)
        return page

    def _build_hikvision_page(self) -> QWidget:
        u = self._u
        page = QWidget()
        layout = QVBoxLayout(page)
        dev_group = QGroupBox(u.group_device)
        dev_layout = QVBoxLayout(dev_group)
        self._combo_devices = QComboBox()
        self._combo_devices.addItem(u.device_combo_placeholder)
        dev_layout.addWidget(self._combo_devices)
        btn_enum = QPushButton(u.btn_enum_devices)
        btn_enum.clicked.connect(self._cb("on_enum_devices"))
        dev_layout.addWidget(btn_enum)
        row_open = QHBoxLayout()
        self._btn_open = QPushButton(u.btn_open)
        self._btn_open.clicked.connect(self._on_hikvision_open)
        self._btn_close = QPushButton(u.btn_close)
        self._btn_close.clicked.connect(self._cb("on_close"))
        row_open.addWidget(self._btn_open)
        row_open.addWidget(self._btn_close)
        dev_layout.addLayout(row_open)
        layout.addWidget(dev_group)
        grab_group = QGroupBox(u.group_grabbing)
        grab_layout = QVBoxLayout(grab_group)
        self._btn_start_grabbing = QPushButton(u.btn_start_grabbing)
        self._btn_start_grabbing.clicked.connect(self._on_hikvision_start_grabbing)
        self._btn_stop_grabbing = QPushButton(u.btn_stop_grabbing)
        self._btn_stop_grabbing.clicked.connect(self._cb("on_stop_grabbing"))
        grab_layout.addWidget(self._btn_start_grabbing)
        grab_layout.addWidget(self._btn_stop_grabbing)
        layout.addWidget(grab_group)
        params_group = QGroupBox(u.group_params)
        params_layout = QVBoxLayout(params_group)
        row_fr = QHBoxLayout()
        row_fr.addWidget(QLabel(u.label_frame_rate))
        self._edit_frame_rate = QLineEdit()
        self._edit_frame_rate.setPlaceholderText(u.placeholder_fps)
        self._edit_frame_rate.setMaximumWidth(80)
        row_fr.addWidget(self._edit_frame_rate)
        params_layout.addLayout(row_fr)
        row_exp = QHBoxLayout()
        row_exp.addWidget(QLabel(u.label_exposure))
        self._edit_exposure = QLineEdit()
        self._edit_exposure.setPlaceholderText(u.placeholder_exposure)
        self._edit_exposure.setMaximumWidth(80)
        row_exp.addWidget(self._edit_exposure)
        params_layout.addLayout(row_exp)
        row_gain = QHBoxLayout()
        row_gain.addWidget(QLabel(u.label_gain))
        self._edit_gain = QLineEdit()
        self._edit_gain.setPlaceholderText(u.placeholder_gain)
        self._edit_gain.setMaximumWidth(80)
        row_gain.addWidget(self._edit_gain)
        params_layout.addLayout(row_gain)
        row_btns = QHBoxLayout()
        self._btn_get_params = QPushButton(u.btn_get_parameters)
        self._btn_get_params.clicked.connect(self._cb("on_get_parameters"))
        self._btn_set_params = QPushButton(u.btn_set_parameters)
        self._btn_set_params.clicked.connect(self._on_hikvision_set_params)
        row_btns.addWidget(self._btn_get_params)
        row_btns.addWidget(self._btn_set_params)
        params_layout.addLayout(row_btns)
        layout.addWidget(params_group)
        return page

    def _cb(self, key: str) -> Callable:
        def _f() -> None:
            fn = self._callbacks.get(key)
            if fn:
                fn()
        return _f

    def _on_camera_type_changed(self, index: int) -> None:
        rev_map = {0: "simulator", 1: "webcam", 2: "hikvision"}
        self._camera_type = rev_map.get(index, "simulator")
        rm = self._registers_manager
        if rm and hasattr(rm, "set_field_value"):
            rm.set_field_value(CAMERA_REGISTER, "camera_type", self._camera_type)
            try:
                from multiprocess_prototype.persistence import set_camera_type

                set_camera_type(self._camera_type)
            except Exception:
                pass
        else:
            fn = self._callbacks.get("on_camera_type_changed")
            if fn:
                fn(self._camera_type)
        self._stack.setCurrentIndex(1 if self._camera_type == "hikvision" else 0)

    def _on_fps_changed(self, value: int) -> None:
        if hasattr(self, "_fps_label"):
            self._fps_label.setText(f"{value}{self._u.fps_suffix}")
        fn = self._callbacks.get("on_set_fps")
        if fn:
            fn(value)

    def _get_selected_camera_index(self) -> int:
        idx = self._combo_devices.currentIndex()
        if idx <= 0 or idx > len(self._hikvision_devices):
            return 0
        return self._hikvision_devices[idx - 1].get("index", 0)

    def _on_hikvision_open(self) -> None:
        fn = self._callbacks.get("on_open")
        if fn:
            fn(camera_index=self._get_selected_camera_index())

    def _on_hikvision_start_grabbing(self) -> None:
        fn_open = self._callbacks.get("on_open")
        fn_start = self._callbacks.get("on_start_grabbing")
        if fn_open:
            fn_open(camera_index=self._get_selected_camera_index())
        if fn_start:
            fn_start()

    def _on_hikvision_set_params(self) -> None:
        try:
            fr = float(self._edit_frame_rate.text() or 25)
            exp = float(self._edit_exposure.text() or 10000)
            gain = float(self._edit_gain.text() or 0)
        except ValueError:
            return
        fn = self._callbacks.get("on_set_parameters")
        if fn:
            fn(fr, exp, gain)

    def sync_camera_type(self, camera_type: str) -> None:
        self._camera_type = camera_type
        idx = self._camera_type_map.get(camera_type, 0)
        self._combo_camera_type.blockSignals(True)
        self._combo_camera_type.setCurrentIndex(idx)
        self._combo_camera_type.blockSignals(False)
        self._stack.setCurrentIndex(1 if camera_type == "hikvision" else 0)

    def update_camera_devices(self, devices: list) -> None:
        self._hikvision_devices = devices or []
        self._combo_devices.clear()
        self._combo_devices.addItem(self._u.device_combo_placeholder)
        for dev in self._hikvision_devices:
            display = dev.get("display_name", f"[{dev.get('index', '?')}]")
            self._combo_devices.addItem(display)

    def update_camera_parameters(self, params: dict) -> None:
        if not params:
            return
        if hasattr(self, "_fps_label") and "frame_rate" in params:
            self._fps_label.setText(f"{params['frame_rate']:.1f}{self._u.fps_suffix}")
        if hasattr(self, "_edit_frame_rate"):
            self._edit_frame_rate.setText(f"{params.get('frame_rate', 0):.1f}")
        if hasattr(self, "_edit_exposure"):
            self._edit_exposure.setText(f"{params.get('exposure_time', 0):.0f}")
        if hasattr(self, "_edit_gain"):
            self._edit_gain.setText(f"{params.get('gain', 0):.1f}")
