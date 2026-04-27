# multiprocess_prototype_v3/frontend/widgets/hikvision_widget/presenter.py
"""HikvisionPresenter — связывает Model и View, обрабатывает действия пользователя."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabPresenterBase

from .schemas import HikvisionUiConfig

if TYPE_CHECKING:
    from .model import HikvisionModel
    from .view import HikvisionView


class HikvisionPresenter(TabPresenterBase["HikvisionView", HikvisionUiConfig]):
    """Логика Hikvision: делегирует в Model, обновляет View."""

    def __init__(
        self,
        *,
        view: "HikvisionView",
        model: "HikvisionModel",
        ui: HikvisionUiConfig,
    ) -> None:
        super().__init__(view=view, rm=None, ui=ui)
        self._model = model

    def on_open_clicked(self, camera_index: int) -> None:
        """Обработчик кнопки Open. Индекс передаётся View при клике."""
        self._model.open_camera(camera_index)

    def on_start_grabbing_clicked(self, camera_index: int) -> None:
        """Обработчик Start Grabbing: открыть камеру (если нужно) и начать захват."""
        self._model.open_camera(camera_index)
        self._model.start_grabbing()

    def on_set_parameters_clicked(
        self, frame_rate: float, exposure: float, gain: float
    ) -> None:
        """Обработчик Set Parameters: тройка уже выбрана в Model/View (get_params_for_set)."""
        self._model.set_parameters(frame_rate, exposure, gain)

    def update_camera_devices(self, devices: list) -> None:
        """Обновить список устройств в View (внешний вызов)."""
        self._view.set_devices_list(devices or [])

    def update_camera_parameters(self, params: dict[str, Any]) -> None:
        """Обновить регистр и поля параметров в View (внешний вызов)."""
        if not params:
            return
        self._model.apply_params_to_register(params)
        self._view.set_hikvision_params_lines(params)
