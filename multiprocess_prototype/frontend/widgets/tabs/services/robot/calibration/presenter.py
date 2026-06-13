# -*- coding: utf-8 -*-
"""CalibrationPresenter — команды визарда калибровки (без Qt-виджетов).

Команды cal_* идут в ПРОЦЕСС с плагином ``camera_robot_calibration`` (НЕ в devices —
в отличие от robot/vfd presenter'ов): имя процесса резолвится из активного рецепта
(см. controller.resolve_calibration_process). Команды fire-and-accept: плагин сразу
возвращает ``{"status":"accepted"}``, реальный прогресс приходит подпиской на
``calibration.state.<camera_id>.progress``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_NOOP: Callable[[dict], None] = lambda _r: None  # noqa: E731


class CalibrationPresenter:
    """Презентер визарда калибровки: команды cal_* в target-процесс.

    Зависимости (duck-typed):
        command_sender — CommandSender.request_command(process, cmd, args).
        request_runner — RequestRunner.submit(fn, on_result) (off-main-thread).
        target_process — имя процесса с плагином camera_robot_calibration.
    """

    def __init__(
        self,
        *,
        command_sender: Any = None,
        request_runner: Any = None,
        target_process: str = "cal",
    ) -> None:
        self._sender = command_sender
        self._runner = request_runner
        self._target = target_process

    # ------------------------------------------------------------------ #
    # Команды визарда
    # ------------------------------------------------------------------ #

    def begin(self, camera_id: str, robot_id: str, vfd_id: str, on_result=None) -> None:
        self._request("cal_begin", {"camera_id": camera_id, "robot_id": robot_id, "vfd_id": vfd_id}, on_result)

    def capture_image(self, on_result=None) -> None:
        self._request("cal_capture_image", {}, on_result)

    def set_robot_point(self, index: int, on_result=None) -> None:
        self._request("cal_set_robot_point", {"index": int(index)}, on_result)

    def encoder_scale(self, ref_index: int, on_result=None) -> None:
        self._request("cal_encoder_scale", {"ref_index": int(ref_index)}, on_result)

    def belt_run(self, freq_hz: float, on_result=None) -> None:
        self._request("cal_belt_run", {"freq": float(freq_hz)}, on_result)

    def belt_stop(self, on_result=None) -> None:
        self._request("cal_belt_stop", {}, on_result)

    def compute(self, on_result=None) -> None:
        self._request("cal_compute", {}, on_result)

    def save(self, on_result=None) -> None:
        self._request("cal_save", {}, on_result)

    def reset(self, on_result=None) -> None:
        self._request("cal_reset", {}, on_result)

    # ------------------------------------------------------------------ #

    def _request(self, command: str, args: dict, cb) -> None:
        cb = cb or _NOOP
        if self._sender is None or self._runner is None:
            logger.debug("Calibration: request %s недоступен (нет sender/runner)", command)
            cb({})
            return
        self._runner.submit(
            lambda: self._sender.request_command(self._target, command, args),
            on_result=cb,
        )
