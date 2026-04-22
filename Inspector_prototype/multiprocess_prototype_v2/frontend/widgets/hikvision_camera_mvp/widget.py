# multiprocess_prototype/frontend/widgets/hikvision_camera_mvp/widget.py
"""HikvisionCameraMvpWidget — BaseWidget + MVP; разметка в HikvisionCameraMvpView."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Union

from frontend_module.core.qt_imports import QVBoxLayout
from frontend_module.core.schema_config import coerce_schema_config
from frontend_module.widgets.base_widget import BaseWidget
from frontend_module.widgets.tabs import callback_no_args

from multiprocess_prototype_v2.registers.camera import WEBCAM_ENUM_DEFAULT_MAX_INDEX

from .model import HikvisionCameraMvpModel
from .presenter import HikvisionCameraMvpPresenter
from .schemas import HikvisionCameraMvpUiConfig
from .view import HikvisionCameraMvpView

if TYPE_CHECKING:
    from multiprocess_prototype_v2.frontend.commands.gui_command_handler import GuiCommandHandler


class HikvisionCameraMvpWidget(BaseWidget[HikvisionCameraMvpModel]):
    """Hikvision: устройство, Open/Close, Grabbing, параметры (MVP)."""

    def __init__(
        self,
        *,
        command_handler: GuiCommandHandler,
        registers_manager=None,
        ui: Optional[Union[HikvisionCameraMvpUiConfig, dict]] = None,
        touch_keyboard: Any | None = None,
        webcam_enum_max_index: int = WEBCAM_ENUM_DEFAULT_MAX_INDEX,
        parent=None,
    ) -> None:
        self._command_handler = command_handler
        self._webcam_enum_max_index = int(webcam_enum_max_index)
        self._touch_keyboard_parent = touch_keyboard
        super().__init__(
            registers_manager=registers_manager,
            callbacks=None,
            ui=ui,
            parent=parent,
        )

    def _coerce_callbacks(self, callbacks: Optional[object]) -> Any:
        return None

    def _coerce_ui(self, ui: Optional[object]) -> HikvisionCameraMvpUiConfig:
        return coerce_schema_config(ui, HikvisionCameraMvpUiConfig)

    def _create_model(self) -> HikvisionCameraMvpModel:
        return HikvisionCameraMvpModel(
            rm=self._registers_manager,
            ui=self._ui,
        )

    def _init_ui(self) -> None:
        assert self._model is not None
        self._view = HikvisionCameraMvpView(
            self,
            registers_manager=self._registers_manager,
            ui=self._ui,
            touch_keyboard_parent=self._touch_keyboard_parent,
            param_rows=self._model.param_rows,
        )
        root = QVBoxLayout(self)
        root.addWidget(self._view)

    def _create_presenter(self, model: Optional[HikvisionCameraMvpModel]) -> HikvisionCameraMvpPresenter:
        assert model is not None
        return HikvisionCameraMvpPresenter(
            view=self._view,
            model=model,
            ui=self._ui,
            command_handler=self._command_handler,
            webcam_enum_max_index=self._webcam_enum_max_index,
        )

    def _connect_signals(self) -> None:
        _btn = callback_no_args
        p = self._presenter
        v = self._view
        v.btn_enum.clicked.connect(_btn(p.on_enum_devices))
        v.btn_open.clicked.connect(self._on_open_clicked)
        v.btn_close.clicked.connect(_btn(p.on_close_camera))
        v.btn_start_grabbing.clicked.connect(self._on_start_grabbing_clicked)
        v.btn_stop_grabbing.clicked.connect(_btn(p.on_stop_grabbing))
        v.btn_get_parameters.clicked.connect(_btn(p.on_get_parameters))
        v.btn_set_parameters.clicked.connect(_btn(p.on_set_parameters_clicked))

    def _on_open_clicked(self) -> None:
        self._presenter.on_open_clicked(self._view.selected_camera_index())

    def _on_start_grabbing_clicked(self) -> None:
        self._presenter.on_start_grabbing_clicked(self._view.selected_camera_index())

    def update_camera_devices(self, devices: list) -> None:
        self._presenter.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        self._presenter.update_camera_parameters(params)
