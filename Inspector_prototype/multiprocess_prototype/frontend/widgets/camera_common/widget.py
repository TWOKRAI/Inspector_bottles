# multiprocess_prototype/frontend/widgets/camera_common/widget.py
"""
SimWebcamWidget — Simulator и Webcam: один UI.

Режим (simulator vs webcam) задаёт вкладка камеры через регистр и стек из двух
экземпляров; camera_type_id отличает страницу в QStackedWidget.
"""

from __future__ import annotations

from typing import Literal, Optional, Union

from frontend_module.components import BaseTab
from frontend_module.components.tabs import RegisterBindingContext
from frontend_module.core.qt_imports import QVBoxLayout
from frontend_module.core.schema_config import coerce_schema_config

from .binder import bind_sim_webcam_ui
from .callbacks import SimWebcamWidgetCallbacks
from .presenter import SimWebcamPresenter
from .schemas import SimWebcamUiConfig

CameraTypeId = Literal["simulator", "webcam"]


class SimWebcamWidget(BaseTab):
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
        super().__init__(parent)
        self._camera_type_id = camera_type_id
        self._registers_manager = registers_manager
        self._callbacks = callbacks or SimWebcamWidgetCallbacks()
        self._ui = coerce_schema_config(ui, SimWebcamUiConfig)
        self._fps_refs = None

        binding = RegisterBindingContext(rm=self._registers_manager)
        self._presenter = SimWebcamPresenter(
            view=self,
            rm=self._registers_manager,
            ui=self._ui,
            callbacks=self._callbacks,
        )
        self._page, self._fps_refs = bind_sim_webcam_ui(
            self._ui,
            binding,
            self._callbacks,
            self._presenter,
        )
        root = QVBoxLayout(self)
        root.addWidget(self._page)

    def set_fps_label_text(self, text: str) -> None:
        if self._fps_refs and self._fps_refs.label is not None:
            self._fps_refs.label.setText(text)

    @property
    def camera_type_id(self) -> CameraTypeId:
        return self._camera_type_id

    @property
    def registers_manager(self):
        return self._registers_manager
