# multiprocess_prototype_v3/frontend/widgets/camera_common/presenter.py
"""Презентер Simulator/Webcam: FPS и колбэки."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from frontend_module.widgets.tabs import TabPresenterBase
from frontend_module.interfaces import IRegistersManagerGui

from .schemas import SimWebcamUiConfig

if TYPE_CHECKING:
    from .callbacks import SimWebcamWidgetCallbacks
    from .view import SimWebcamView


class SimWebcamPresenter(TabPresenterBase["SimWebcamView", SimWebcamUiConfig]):
    """on_fps_changed → подпись FPS, колбэк."""

    def __init__(
        self,
        *,
        view: "SimWebcamView",
        rm: Optional[IRegistersManagerGui],
        ui: SimWebcamUiConfig,
        callbacks: "SimWebcamWidgetCallbacks",
    ):
        super().__init__(view=view, rm=rm, ui=ui)
        self._callbacks = callbacks

    def on_fps_changed(self, value: int) -> None:
        """Обновить подпись FPS и при наличии вызвать on_set_fps (команда в бэкенд)."""
        self._view.set_fps_label_text(f"{value}{self._ui.fps_suffix}")
        if self._callbacks.on_set_fps:
            self._callbacks.on_set_fps(value)
