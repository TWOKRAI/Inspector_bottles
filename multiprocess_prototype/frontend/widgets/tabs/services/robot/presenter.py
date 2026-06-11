# -*- coding: utf-8 -*-
"""RobotPresenter — логика секции «Робот Delta» (без Qt-виджетов).

Команды трём плагинам одного процесса-ноды робота (co-location: robot_io —
владелец соединения, vfd_control и robot_draw — потребители):

- fire-and-forget (send_test_job/abort/set_mode/servo/vfd_run/draw_*) — через
  ``topology_bridge.on_action_command`` (ответ не нужен, статус придёт опросом);
- request/response (get_telemetry/get_vfd_status/get_draw_progress/read_echo/
  get_robot_config) — через ``CommandSender.request_command`` на worker-потоке
  (``RequestRunner``), результат в main-thread.

UX-ограничения протокола (см. план robot-vfd-services):
- переключатель CVT/DRAW активен только при free=1;
- VFD-кнопки дизейблятся в DRAW-режиме (Lua не обслуживает VFD_FLAG в DRAW);
- «связь жива» — по успешности чтений, НЕ по TLM-heartbeat (он стоит в job/draw).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PLUGIN_IO = "robot_io"
_PLUGIN_VFD = "vfd_control"
_PLUGIN_DRAW = "robot_draw"


class RobotPresenter:
    """Презентер робота/ПЧ: live-команды плагинам + request/response статусы.

    Зависимости (duck-typed, любая может быть None → graceful degradation):
        bridge          — TopologyBridge.on_action_command(plugin, cmd, args).
        topology        — TopologyRepository.load().to_dict() (поиск процесса робота).
        command_sender  — CommandSender.request_command(process, cmd, args).
        request_runner  — RequestRunner.submit(fn, on_result) (off-main-thread).
    """

    def __init__(
        self,
        *,
        bridge: Any = None,
        topology: Any = None,
        command_sender: Any = None,
        request_runner: Any = None,
    ) -> None:
        self._bridge = bridge
        self._topology = topology
        self._sender = command_sender
        self._runner = request_runner

    # ------------------------------------------------------------------ #
    # Топология
    # ------------------------------------------------------------------ #

    def robot_process_name(self) -> str | None:
        """Имя процесса, содержащего плагин robot_io (нода робота). None если нет."""
        if self._topology is None:
            return None
        try:
            topo = self._topology.load().to_dict()
        except Exception:
            return None
        for proc in topo.get("processes", []):
            for p in proc.get("plugins", []):
                name = p.get("plugin_name") if isinstance(p, dict) else str(p)
                if name == _PLUGIN_IO:
                    return proc.get("process_name")
        return None

    @property
    def is_live(self) -> bool:
        """True если есть мост и нода робота в активном рецепте."""
        return self._bridge is not None and self.robot_process_name() is not None

    # ------------------------------------------------------------------ #
    # Робот: CVT / режим / конфиг (fire-and-forget)
    # ------------------------------------------------------------------ #

    def send_test_job(self, x_mm: float, y_mm: float) -> bool:
        """Тестовое CVT-задание в очередь feeder."""
        return self._send(_PLUGIN_IO, "send_test_job", {"x": float(x_mm), "y": float(y_mm)})

    def abort(self, mode: int) -> bool:
        """Стоп робота: 1=домой+цикл, 2=домой+выход, 3=на месте."""
        return self._send(_PLUGIN_IO, "abort", {"mode": int(mode)})

    def set_mode(self, mode: str) -> bool:
        """Режим cvt|draw (переключать только при free)."""
        return self._send(_PLUGIN_IO, "set_mode", {"mode": mode})

    def set_servo(self, on: bool) -> bool:
        """Серво ON/OFF."""
        return self._send(_PLUGIN_IO, "set_servo", {"on": bool(on)})

    def set_manual_mode(self, on: bool) -> bool:
        """Ручной режим: пауза авто-подачи заданий (P2.5)."""
        return self._send(_PLUGIN_IO, "set_manual_mode", {"on": bool(on)})

    def set_robot_config(self, fields: dict[str, float]) -> bool:
        """Конфиг робота (speed/home_*/place_*/pick_z/zone_*/grip_ms)."""
        return self._send(_PLUGIN_IO, "set_robot_config", fields)

    # ------------------------------------------------------------------ #
    # ПЧ (fire-and-forget)
    # ------------------------------------------------------------------ #

    def vfd_run(self, freq_hz: float, reverse: bool = False) -> bool:
        """Запустить ленту."""
        return self._send(_PLUGIN_VFD, "vfd_run", {"freq": float(freq_hz), "reverse": bool(reverse)})

    def vfd_set_freq(self, freq_hz: float) -> bool:
        """Сменить частоту на ходу."""
        return self._send(_PLUGIN_VFD, "vfd_set_freq", {"hz": float(freq_hz)})

    def vfd_stop(self) -> bool:
        """Остановить ленту."""
        return self._send(_PLUGIN_VFD, "vfd_stop", {})

    def vfd_reset_fault(self) -> bool:
        """Сбросить аварию ПЧ."""
        return self._send(_PLUGIN_VFD, "vfd_reset_fault", {})

    # ------------------------------------------------------------------ #
    # Рисование (fire-and-forget — исполняется асинхронно worker'ом плагина)
    # ------------------------------------------------------------------ #

    def draw_circle(self, cx: float, cy: float, r: float, z: float) -> bool:
        """Круг родным MCircle."""
        return self._send(_PLUGIN_DRAW, "draw_circle", {"cx": float(cx), "cy": float(cy), "r": float(r), "z": float(z)})

    def draw_square(self, x1: float, y1: float, x2: float, y2: float, z: float) -> bool:
        """Прямоугольник по углам ЛВ и ПН."""
        return self._send(
            _PLUGIN_DRAW,
            "draw_square",
            {"x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2), "z": float(z)},
        )

    def set_pen(self, down_mm: float, up_mm: float) -> bool:
        """Высоты пера."""
        return self._send(_PLUGIN_DRAW, "set_pen", {"down": float(down_mm), "up": float(up_mm)})

    def set_draw_speed(self, pct: int) -> bool:
        """Скорость рисования, %."""
        return self._send(_PLUGIN_DRAW, "set_draw_speed", {"pct": int(pct)})

    def set_overlap(self, mm: float) -> bool:
        """Скругление углов."""
        return self._send(_PLUGIN_DRAW, "set_overlap", {"mm": float(mm)})

    def abort_draw(self) -> bool:
        """Прервать рисование немедленно."""
        return self._send(_PLUGIN_DRAW, "abort_draw", {})

    # ------------------------------------------------------------------ #
    # Request/response — статусы (результат в main-thread)
    # ------------------------------------------------------------------ #

    def get_telemetry(self, on_result: Callable[[dict], None]) -> None:
        """Телеметрия робота: {telemetry, free, encoder, queue_len}."""
        self._request("get_telemetry", lambda r: on_result(r if isinstance(r, dict) else {}))

    def get_vfd_status(self, on_result: Callable[[dict], None]) -> None:
        """Статус ПЧ (свежий poll): {vfd: {...}, bridge_alive}."""
        self._request("get_vfd_status", lambda r: on_result(r if isinstance(r, dict) else {}))

    def get_draw_progress(self, on_result: Callable[[dict], None]) -> None:
        """Прогресс рисования: {state, busy, progress_point, ...}."""
        self._request("get_draw_progress", lambda r: on_result(r if isinstance(r, dict) else {}))

    def read_echo(self, on_result: Callable[[dict], None]) -> None:
        """Эхо последнего принятого задания."""
        self._request("read_echo", lambda r: on_result(r if isinstance(r, dict) else {}))

    def get_robot_config(self, on_result: Callable[[dict], None]) -> None:
        """Конфиг-блок робота."""
        self._request("get_robot_config", lambda r: on_result(r if isinstance(r, dict) else {}))

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _send(self, plugin: str, command: str, args: dict) -> bool:
        if self._bridge is None:
            logger.debug("Robot: bridge недоступен — %s.%s пропущена", plugin, command)
            return False
        try:
            return bool(self._bridge.on_action_command(plugin, command, args))
        except Exception as exc:
            logger.warning("Robot: команда %s.%s провалилась: %s", plugin, command, exc)
            return False

    def _request(self, command: str, cb: Callable[[dict], None]) -> None:
        proc = self.robot_process_name()
        if self._sender is None or self._runner is None or proc is None:
            logger.debug("Robot: request %s недоступен (нет sender/runner/процесса)", command)
            cb({})
            return
        self._runner.submit(
            lambda: self._sender.request_command(proc, command, {}),
            on_result=lambda r: cb(_unwrap(r)),
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
