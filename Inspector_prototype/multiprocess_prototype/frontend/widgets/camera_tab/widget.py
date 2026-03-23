# multiprocess_prototype/frontend/widgets/camera_tab/widget.py
"""
CameraTabWidget — вкладка управления камерой.

Реализует CameraTabView; делегирует логику CameraTabPresenter.
Использует MvpTabBase для унификации MVP-вкладок.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Union

from frontend_module.components.tabs import (
    MvpTabBase,
    RegisterBindingContext,
    callback_no_args,
)
from frontend_module.core.qt_imports import QComboBox, QGroupBox, QStackedWidget, QVBoxLayout, QWidget

from .callbacks import CameraTabCallbacks
from .pages.hikvision import HikvisionPageRefs, build_hikvision_page
from .pages.sim_webcam import SimWebcamPageRefs, build_sim_webcam_page
from .presenter import CameraTabPresenter
from .schemas import CameraTabUiConfig
from .ui_coerce import coerce_camera_ui


class CameraTabWidget(MvpTabBase):
    """
    Вкладка камеры: Simulator/Webcam/Hikvision.
    """

    def __init__(
        self,
        *,
        camera_type: str = "simulator",
        registers_manager: Optional[Any] = None,
        callbacks: Optional[Union[CameraTabCallbacks, Dict[str, Callable]]] = None,
        ui: Optional[Union[CameraTabUiConfig, dict]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(
            registers_manager=registers_manager,
            callbacks=callbacks,
            ui=ui,
            parent=parent,
            camera_type=camera_type,
        )

    def _coerce_callbacks(self, callbacks: Optional[Any]) -> CameraTabCallbacks:
        if isinstance(callbacks, dict):
            return CameraTabCallbacks.from_dict(callbacks)
        return callbacks or CameraTabCallbacks()

    def _coerce_ui(self, ui: Optional[Any]) -> CameraTabUiConfig:
        return coerce_camera_ui(ui)

    def _create_presenter(self) -> CameraTabPresenter:
        return CameraTabPresenter(
            view=self,
            callbacks=self._callbacks,
            rm=self._registers_manager,
            ui=self._ui,
        )

    def _on_presenter_ready(self, camera_type: str = "simulator", **kwargs: Any) -> None:
        self._presenter.sync_camera_type(camera_type)

    def _init_ui(self) -> None:
        """Собирает UI: выбор типа камеры, стек (Sim/Web | Hikvision), колбэки через callback_no_args."""
        self._hikvision_devices = []
        self._sim_refs = None
        self._hik_refs = None
        u = self._ui
        root = QVBoxLayout(self)

        # Тип камеры — ComboBox, индекс → camera_type в регистре
        type_group = QGroupBox(u.group_camera_type)
        type_layout = QVBoxLayout(type_group)
        self._combo_camera_type = QComboBox()
        self._combo_camera_type.addItems(list(u.camera_type_options))
        self._combo_camera_type.setMinimumWidth(u.camera_type_combo_min_width)
        self._combo_camera_type.currentIndexChanged.connect(self._on_camera_type_changed)
        type_layout.addWidget(self._combo_camera_type)
        root.addWidget(type_group)

        # Стек: индекс 0 = Simulator/Webcam, индекс 1 = Hikvision
        self._stack = QStackedWidget()
        binding = RegisterBindingContext(rm=self._registers_manager)
        _cb = self._callbacks
        _btn = callback_no_args
        sim_page, self._sim_refs = build_sim_webcam_page(
            u,
            binding,
            on_start=_btn(_cb.on_start),
            on_stop=_btn(_cb.on_stop),
            on_fps_slider_changed=self._on_fps_changed,
        )
        hik_page, self._hik_refs = build_hikvision_page(
            u,
            binding,
            on_enum_devices=_btn(_cb.on_enum_devices),
            on_open=self._on_hikvision_open,
            on_close=_btn(_cb.on_close),
            on_start_grabbing=self._on_hikvision_start_grabbing,
            on_stop_grabbing=_btn(_cb.on_stop_grabbing),
            on_get_parameters=_btn(_cb.on_get_parameters),
            on_set_parameters_clicked=self._on_hikvision_set_params,
        )
        self._stack.addWidget(sim_page)
        self._stack.addWidget(hik_page)
        root.addWidget(self._stack)
        root.addStretch()

    # --- CameraTabView ---

    def set_camera_type_combo_index(self, index: int) -> None:
        self._combo_camera_type.blockSignals(True)
        self._combo_camera_type.setCurrentIndex(index)
        self._combo_camera_type.blockSignals(False)

    def set_stack_index(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def set_fps_label_text(self, text: str) -> None:
        if self._sim_refs and self._sim_refs.fps.label is not None:
            self._sim_refs.fps.label.setText(text)

    def get_selected_camera_index(self) -> int:
        if not self._hik_refs:
            return 0
        idx = self._hik_refs.combo_devices.currentIndex()
        if idx <= 0 or idx > len(self._hikvision_devices):
            return 0
        return self._hikvision_devices[idx - 1].get("index", 0)

    def set_devices_list(self, devices: list) -> None:
        self._hikvision_devices = devices or []
        if not self._hik_refs:
            return
        combo = self._hik_refs.combo_devices
        combo.clear()
        combo.addItem(self._ui.device_combo_placeholder)
        for dev in self._hikvision_devices:
            display = dev.get("display_name", f"[{dev.get('index', '?')}]")
            combo.addItem(display)

    def set_hikvision_params_lines(self, params: dict) -> None:
        if not self._hik_refs:
            return
        for m, ed in zip(self._ui.hikvision_api_to_register, self._hik_refs.hik_params.line_edits):
            if ed is None:
                continue
            raw = float(params.get(m.api_key, 0))
            ed.setText(format(raw, m.line_edit_format_spec))

    def get_hikvision_params_from_lines(self) -> tuple[float, float, float]:
        hp = self._hik_refs.hik_params if self._hik_refs else None
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

    def _on_camera_type_changed(self, index: int) -> None:
        """Обработчик ComboBox: записывает в регистр, переключает страницу стека."""
        self._presenter.on_camera_type_changed(index)

    def _on_fps_changed(self, value: int) -> None:
        self._presenter.on_fps_changed(value)

    def _on_hikvision_open(self) -> None:
        """Открыть устройство: передаёт индекс из ComboBox в on_open."""
        self._presenter.on_hikvision_open()

    def _on_hikvision_start_grabbing(self) -> None:
        """Open + Start Grabbing (обёртка для двух колбэков)."""
        self._presenter.on_hikvision_start_grabbing()

    def _on_hikvision_set_params(self) -> None:
        """Читает triple из регистра или line edits, вызывает on_set_parameters."""
        self._presenter.on_hikvision_set_parameters_clicked()

    def sync_camera_type(self, camera_type: str) -> None:
        self._presenter.sync_camera_type(camera_type)

    def update_camera_devices(self, devices: list) -> None:
        self._presenter.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        self._presenter.update_camera_parameters(params)
