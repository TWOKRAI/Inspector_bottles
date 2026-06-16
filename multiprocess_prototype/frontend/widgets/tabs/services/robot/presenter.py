# -*- coding: utf-8 -*-
"""RobotPresenter — логика секции «Робот Delta» (без Qt-виджетов).

Фаза 4 device-hub: все команды → target process ``devices``, имена
``robot_*/robot_draw_*`` (из DeviceHubPlugin.commands), каждая с
``device_id`` выбранного устройства. Резолв процесса по топологии
убран — ``devices`` always-on.

Команды:
  - request/response (robot_get_telemetry/robot_get_robot_config/
    robot_draw_progress/robot_read_echo) — через ``CommandSender.request_command``
    на worker-потоке (``RequestRunner``), результат в main-thread.
  - Остальные — тоже request (нужен status ответа для UX).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TARGET = "devices"


class RobotPresenter:
    """Презентер робота: команды через процесс ``devices`` + request/response.

    Зависимости (duck-typed, любая может быть None -> graceful degradation):
        command_sender  — CommandSender.request_command(process, cmd, args).
        request_runner  — RequestRunner.submit(fn, on_result) (off-main-thread).
    """

    def __init__(
        self,
        *,
        command_sender: Any = None,
        request_runner: Any = None,
    ) -> None:
        self._sender = command_sender
        self._runner = request_runner

    # ------------------------------------------------------------------ #
    # Робот: CVT / режим / конфиг
    # ------------------------------------------------------------------ #

    def send_test_job(self, device_id: str, x_mm: float, y_mm: float, z_mm: float = 0.0) -> None:
        """Тестовое CVT-задание в очередь feeder. z=глубина захвата (0 = дефолт прошивки Z_PICK)."""
        self._request(
            "robot_send_test_job",
            {"device_id": device_id, "x": float(x_mm), "y": float(y_mm), "z": float(z_mm)},
        )

    def abort(self, device_id: str, mode: int) -> None:
        """Стоп робота: 1=домой+цикл, 2=домой+выход, 3=на месте."""
        self._request("robot_abort", {"device_id": device_id, "mode": int(mode)})

    def set_mode(self, device_id: str, mode: str) -> None:
        """Режим cvt|draw (переключать только при free)."""
        self._request("robot_set_mode", {"device_id": device_id, "mode": mode})

    def set_servo(self, device_id: str, on: bool) -> None:
        """Серво ON/OFF."""
        self._request("robot_set_servo", {"device_id": device_id, "on": bool(on)})

    def jog(self, device_id: str, dx: float, dy: float, spd: int, absolute: bool) -> None:
        """Ручной ход: смещение dX/dY (мм) при скорости spd (Override %). Включает mode=manual."""
        self._request(
            "robot_jog",
            {"device_id": device_id, "dx": float(dx), "dy": float(dy), "spd": int(spd), "absolute": bool(absolute)},
        )

    def jog_abort(self, device_id: str) -> None:
        """Прервать ручной ход."""
        self._request("robot_jog_abort", {"device_id": device_id})

    def set_manual_mode(self, device_id: str, on: bool) -> None:
        """Ручной режим: пауза авто-подачи заданий."""
        self._request("robot_set_manual_mode", {"device_id": device_id, "on": bool(on)})

    def set_robot_config(self, device_id: str, fields: dict[str, float]) -> None:
        """Конфиг робота (speed/home_*/place_*/pick_z/zone_*/grip_ms)."""
        self._request("robot_set_robot_config", {"device_id": device_id, **fields})

    def clear_queue(self, device_id: str) -> None:
        """Очистить очередь заданий."""
        self._request("robot_clear_queue", {"device_id": device_id})

    # ------------------------------------------------------------------ #
    # Рисование
    # ------------------------------------------------------------------ #

    def draw_circle(self, device_id: str, cx: float, cy: float, r: float, z: float) -> None:
        """Круг родным MCircle."""
        self._request(
            "robot_draw_circle",
            {"device_id": device_id, "cx": float(cx), "cy": float(cy), "r": float(r), "z": float(z)},
        )

    def draw_square(self, device_id: str, x1: float, y1: float, x2: float, y2: float, z: float) -> None:
        """Прямоугольник по углам ЛВ и ПН."""
        self._request(
            "robot_draw_square",
            {
                "device_id": device_id,
                "x1": float(x1),
                "y1": float(y1),
                "x2": float(x2),
                "y2": float(y2),
                "z": float(z),
            },
        )

    def set_pen(self, device_id: str, down_mm: float, up_mm: float) -> None:
        """Высоты пера."""
        self._request("robot_draw_set_pen", {"device_id": device_id, "down": float(down_mm), "up": float(up_mm)})

    def set_draw_speed(self, device_id: str, pct: int) -> None:
        """Скорость рисования, %."""
        self._request("robot_draw_set_speed", {"device_id": device_id, "pct": int(pct)})

    def set_overlap(self, device_id: str, mm: float) -> None:
        """Скругление углов."""
        self._request("robot_draw_set_overlap", {"device_id": device_id, "mm": float(mm)})

    def abort_draw(self, device_id: str) -> None:
        """Прервать рисование немедленно."""
        self._request("robot_draw_abort", {"device_id": device_id})

    # ------------------------------------------------------------------ #
    # Портрет (рецепт webcam_sketch) — команды процессам pipeline, НЕ в devices
    # ------------------------------------------------------------------ #

    def _request_to(
        self,
        process_name: str,
        command: str,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Команда произвольному процессу pipeline (не ``devices``)."""
        if self._sender is None or self._runner is None:
            logger.debug("Robot: команда %s недоступна (нет sender/runner)", command)
            if on_result:
                on_result({})
            return
        self._runner.submit(
            lambda: self._sender.request_command(process_name, command, {}),
            on_result=on_result,
        )

    def freeze_camera(self, process_name: str = "camera_0", on_result: Callable[[dict], None] | None = None) -> None:
        """Заморозить кадр камеры (тюнинг на статике)."""
        self._request_to(process_name, "freeze_capture", on_result)

    def resume_camera(self, process_name: str = "camera_0", on_result: Callable[[dict], None] | None = None) -> None:
        """Возобновить живой захват камеры."""
        self._request_to(process_name, "unfreeze_capture", on_result)

    def send_to_robot(self, process_name: str = "points", on_result: Callable[[dict], None] | None = None) -> None:
        """Отправить текущую карту точек роботу (команда robot_draw_send)."""
        self._request_to(process_name, "robot_draw_send", on_result)

    # ------------------------------------------------------------------ #
    # Request/response — статусы (результат в main-thread)
    # ------------------------------------------------------------------ #

    def get_telemetry(self, device_id: str, on_result: Callable[[dict], None]) -> None:
        """Телеметрия робота: {telemetry, free, encoder, queue_len}."""
        self._request(
            "robot_get_telemetry",
            {"device_id": device_id},
            lambda r: on_result(_unwrap(r)),
        )

    def get_draw_progress(self, device_id: str, on_result: Callable[[dict], None]) -> None:
        """Прогресс рисования: {state, busy, progress_point, ...}."""
        self._request(
            "robot_draw_progress",
            {"device_id": device_id},
            lambda r: on_result(_unwrap(r)),
        )

    def read_echo(self, device_id: str, on_result: Callable[[dict], None]) -> None:
        """Эхо последнего принятого задания."""
        self._request(
            "robot_read_echo",
            {"device_id": device_id},
            lambda r: on_result(_unwrap(r)),
        )

    def get_robot_config(self, device_id: str, on_result: Callable[[dict], None]) -> None:
        """Конфиг-блок робота."""
        self._request(
            "robot_get_robot_config",
            {"device_id": device_id},
            lambda r: on_result(_unwrap(r)),
        )

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _request(
        self,
        command: str,
        args: dict,
        cb: Callable[[dict], None] | None = None,
    ) -> None:
        if self._sender is None or self._runner is None:
            logger.debug("Robot: request %s недоступен (нет sender/runner)", command)
            if cb:
                cb({})
            return
        self._runner.submit(
            lambda: self._sender.request_command(_TARGET, command, args),
            on_result=cb,
        )


def _unwrap(response: Any) -> dict:
    """Развернуть ответ request_command: {...} или {"result": {...}}."""
    if not isinstance(response, dict):
        return {}
    inner = response.get("result")
    if isinstance(inner, dict) and "status" not in response:
        return inner
    if isinstance(inner, dict) and set(response) <= {"result", "status", "request_id", "command"}:
        return inner
    return response
