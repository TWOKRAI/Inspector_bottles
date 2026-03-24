# multiprocess_prototype/frontend/widgets/camera_common/widget.py
"""
SimWebcamWidget — Simulator и Webcam: один UI (BaseWidget + MVP + Model).

Режим (simulator vs webcam) задаёт вкладка камеры через регистр и стек из двух
экземпляров; camera_type_id отличает страницу в QStackedWidget.
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from frontend_module.widgets.base_widget import BaseWidget
from frontend_module.widgets.tabs import RegisterBindingContext
from frontend_module.core.qt_imports import QVBoxLayout
from frontend_module.core.schema_config import coerce_schema_config

from .binder import bind_sim_webcam_ui
from .callbacks import SimWebcamWidgetCallbacks
from .model import CameraTypeId, SimWebcamModel
from .presenter import SimWebcamPresenter
from .schemas import SimWebcamUiConfig


class SimWebcamWidget(BaseWidget[SimWebcamModel]):
    """Start, Stop, FPS — для симулятора или веб-камеры (тип камеры в регистре задаёт вкладка)."""

    def __init__(
        self,
        *,
        camera_type_id: CameraTypeId,
        registers_manager=None,
        callbacks: Optional[SimWebcamWidgetCallbacks] = None,
        ui: Optional[Union[SimWebcamUiConfig, dict]] = None,
        parent=None,
    ):
        self._camera_type_id = camera_type_id
        super().__init__(
            registers_manager=registers_manager,
            callbacks=callbacks,
            ui=ui,
            parent=parent,
        )

    def _coerce_callbacks(self, callbacks: Optional[object]) -> SimWebcamWidgetCallbacks:
        return callbacks or SimWebcamWidgetCallbacks()

    def _coerce_ui(self, ui: Optional[object]) -> SimWebcamUiConfig:
        return coerce_schema_config(ui, SimWebcamUiConfig)

    def _create_model(self) -> SimWebcamModel:
        return SimWebcamModel(
            camera_type_id=self._camera_type_id,
            rm=self._registers_manager,
            callbacks=self._callbacks,
            ui=self._ui,
        )

    def _init_ui(self) -> None:
        m = self._model
        assert m is not None
        binding = RegisterBindingContext(rm=m.registers_manager)
        self._page, self._fps_refs = bind_sim_webcam_ui(
            m.ui,
            binding,
            m.callbacks,
            fps_changed=self._fps_changed_slot,
        )
        root = QVBoxLayout(self)
        root.addWidget(self._page)

    def _create_presenter(self, model: Optional[SimWebcamModel]) -> SimWebcamPresenter:
        assert model is not None
        return SimWebcamPresenter(
            view=self,
            rm=model.registers_manager,
            ui=model.ui,
            callbacks=model.callbacks,
        )

    def _connect_signals(self) -> None:
        """Start/Stop/FPS привязаны в binder; дополнительных связей нет."""
        pass

    def _fps_changed_slot(self, value: int) -> None:
        if self._presenter is not None:
            self._presenter.on_fps_changed(value)

    def set_fps_label_text(self, text: str) -> None:
        if self._fps_refs and self._fps_refs.label is not None:
            self._fps_refs.label.setText(text)

    @property
    def camera_type_id(self) -> CameraTypeId:
        return self._camera_type_id
