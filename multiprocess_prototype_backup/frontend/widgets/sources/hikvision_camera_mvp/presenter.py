# multiprocess_prototype/frontend/widgets/hikvision_camera_mvp/presenter.py
"""Презентер: GuiCommandHandler + модель + обновление View."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabPresenterBase

from .schemas import HikvisionCameraMvpUiConfig

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.commands.gui_command_handler import GuiCommandHandler

    from .model import HikvisionCameraMvpModel
    from .view import HikvisionCameraMvpView


class HikvisionCameraMvpPresenter(TabPresenterBase["HikvisionCameraMvpView", HikvisionCameraMvpUiConfig]):
    def __init__(
        self,
        *,
        view: HikvisionCameraMvpView,
        model: HikvisionCameraMvpModel,
        ui: HikvisionCameraMvpUiConfig,
        command_handler: GuiCommandHandler,
        webcam_enum_max_index: int,
    ) -> None:
        super().__init__(view=view, rm=None, ui=ui)
        self._model = model
        self._cmd = command_handler
        self._webcam_enum_max_index = webcam_enum_max_index

    def on_enum_devices(self) -> None:
        self._cmd.send_enum_devices(
            max_index=self._webcam_enum_max_index,
            backend="hikvision",
        )

    def on_open_camera(self, camera_index: int) -> None:
        self._cmd.send_open_camera(camera_index=camera_index)

    def on_close_camera(self) -> None:
        self._cmd.send_close_camera()

    def on_start_grabbing(self) -> None:
        self._cmd.send_start_grabbing()

    def on_stop_grabbing(self) -> None:
        self._cmd.send_stop_grabbing()

    def on_get_parameters(self) -> None:
        self._cmd.send_get_parameters()

    def on_open_clicked(self, camera_index: int) -> None:
        self.on_open_camera(camera_index)

    def on_start_grabbing_clicked(self, camera_index: int) -> None:
        self.on_open_camera(camera_index)
        self.on_start_grabbing()

    def on_set_parameters_clicked(self) -> None:
        raw = self._model.get_params_for_set(self._view.get_params_from_lines)
        issues = self._model.parameters_out_of_range(raw)
        if issues:
            self._view.show_error(
                self._ui.group_params,
                "\n".join(issues),
            )
            return
        clamped = self._model.clamp_parameters(raw)
        fr, exp, gain = clamped[0], clamped[1], clamped[2]
        self._cmd.send_set_parameters(fr, exp, gain)
        rows = self._model.param_rows
        payload = {
            rows[i].api_key: clamped[i]
            for i in range(min(len(clamped), len(rows)))
        }
        self._model.apply_params_to_register(payload)
        self._view.set_hikvision_params_lines(payload)

    def update_camera_devices(self, devices: list) -> None:
        self._view.set_devices_list(devices or [])

    def update_camera_parameters(self, params: dict[str, Any]) -> None:
        if not params:
            return
        self._model.apply_params_to_register(params)
        self._view.set_hikvision_params_lines(params)
