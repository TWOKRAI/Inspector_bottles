# multiprocess_prototype_v3/frontend/widgets/camera_common/model.py
"""SimWebcamModel — данные вкладки Simulator/Webcam (регистры, колбэки, конфиг)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

from .schemas import SimWebcamUiConfig

if TYPE_CHECKING:
    from .callbacks import SimWebcamWidgetCallbacks

CameraTypeId = Literal["simulator", "webcam"]


class SimWebcamModel:
    """Слой данных: тип камеры, rm, колбэки, UI-конфиг."""

    def __init__(
        self,
        *,
        camera_type_id: CameraTypeId,
        rm: Optional[IRegistersManagerGui],
        callbacks: "SimWebcamWidgetCallbacks",
        ui: SimWebcamUiConfig,
    ) -> None:
        """Слой данных вкладки Simulator/Webcam."""
        self._camera_type_id = camera_type_id
        self._rm = rm
        self._callbacks = callbacks
        self._ui = ui

    @property
    def camera_type_id(self) -> CameraTypeId:
        """Идентификатор страницы (simulator / webcam)."""
        return self._camera_type_id

    @property
    def registers_manager(self) -> Optional[IRegistersManagerGui]:
        """RegistersManager вкладки (может быть None в тестах)."""
        return self._rm

    @property
    def callbacks(self) -> "SimWebcamWidgetCallbacks":
        """Колбэки Start/Stop/Set FPS."""
        return self._callbacks

    @property
    def ui(self) -> SimWebcamUiConfig:
        """Подписи и диапазон FPS."""
        return self._ui
