# -*- coding: utf-8 -*-
"""HikvisionSettingsPresenter — логика секции «Hikvision камера» (без Qt-виджетов).

Дискретные команды плагина ``hikvision``:
  - fire-and-forget (open/close/start_capture/stop_capture/set_parameters) — через
    ``topology_bridge.on_action_command`` (ответ не нужен);
  - request/response (enum_devices/get_parameters) — через
    ``CommandSender.request_command`` на worker-потоке (``RequestRunner``), результат
    доставляется в main-thread.

Изображение идёт в дисплей активного рецепта — секция только управляет камерой.
Кнопка «SDK App» запускает автономное окно ``python -m Services.hikvision_camera``.
"""

from __future__ import annotations

import logging
import subprocess  # nosec B404 — запуск собственного SDK App фиксированной командой
import sys
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_PLUGIN = "hikvision"

# Корень проекта (Inspector_bottles) — чтобы `python -m Services.hikvision_camera` нашёл пакет.
_PROJECT_ROOT = Path(__file__).resolve().parents[6]


class HikvisionSettingsPresenter:
    """Презентер камеры Hikvision: live-команды + request/response + SDK App.

    Зависимости (duck-typed, любая может быть None → graceful degradation):
        bridge          — TopologyBridge.on_action_command(plugin, cmd, args).
        topology        — TopologyRepository.load().to_dict() (поиск процесса камеры).
        command_sender  — CommandSender.request_command(process, cmd, args) (round-trip).
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

    # --- topology ---

    def hikvision_process_name(self) -> str | None:
        """Имя процесса, содержащего плагин ``hikvision``. None если нет."""
        if self._topology is None:
            return None
        try:
            topo = self._topology.load().to_dict()
        except Exception:
            return None
        for proc in topo.get("processes", []):
            for p in proc.get("plugins", []):
                name = p.get("plugin_name") if isinstance(p, dict) else str(p)
                if name == _PLUGIN:
                    return proc.get("process_name")
        return None

    @property
    def is_live(self) -> bool:
        """True если есть мост и процесс камеры (можно слать live-команды)."""
        return self._bridge is not None and self.hikvision_process_name() is not None

    # --- fire-and-forget команды ---

    def open(self, camera_index: int) -> bool:
        return self._send("open", {"camera_index": int(camera_index)})

    def close(self) -> bool:
        return self._send("close", {})

    def start(self) -> bool:
        return self._send("start_capture", {})

    def stop(self) -> bool:
        return self._send("stop_capture", {})

    def set_parameters(self, fps: float, exposure: float, gain: float) -> bool:
        return self._send(
            "set_parameters",
            {"frame_rate": float(fps), "exposure_time": float(exposure), "gain": float(gain)},
        )

    def _send(self, command: str, args: dict) -> bool:
        if self._bridge is None:
            logger.debug("Hikvision: bridge недоступен — %s пропущена", command)
            return False
        try:
            return bool(self._bridge.on_action_command(_PLUGIN, command, args))
        except Exception as exc:
            logger.warning("Hikvision: команда %s провалилась: %s", command, exc)
            return False

    # --- request/response команды (результат в main-thread) ---

    def enum_devices(self, on_result: Callable[[list[dict]], None]) -> None:
        """Запросить список устройств; on_result(list[dict]) в main-thread."""
        self._request("enum_devices", {}, lambda r: on_result(_extract(r, "devices") or []))

    def get_parameters(self, on_result: Callable[[dict], None]) -> None:
        """Запросить параметры; on_result({frame_rate, exposure_time, gain}) в main-thread."""
        self._request("get_parameters", {}, lambda r: on_result(_extract(r, "parameters") or {}))

    def _request(self, command: str, args: dict, cb: Callable[[dict], None]) -> None:
        proc = self.hikvision_process_name()
        if self._sender is None or self._runner is None or proc is None:
            logger.debug("Hikvision: request %s недоступен (нет sender/runner/процесса)", command)
            cb({})
            return
        self._runner.submit(
            lambda: self._sender.request_command(proc, command, args),
            on_result=cb,
        )

    # --- SDK App ---

    def open_sdk_app(self) -> bool:
        """Запустить автономное окно SDK App (python -m Services.hikvision_camera)."""
        try:
            subprocess.Popen(  # nosec B603 — фиксированный cmd, shell=False, без пользовательского ввода
                [sys.executable, "-m", "Services.hikvision_camera"],
                cwd=str(_PROJECT_ROOT),
            )
            return True
        except Exception as exc:
            logger.warning("Hikvision: не удалось запустить SDK App: %s", exc)
            return False


def _extract(response: Any, key: str) -> Any:
    """Достать ``key`` из ответа request_command (возможно обёрнутого в result).

    Ответ может прийти как ``{key: ...}`` или ``{"result": {key: ...}}`` /
    ``{"result": {"...": {key: ...}}}`` — проверяем оба уровня.
    """
    if not isinstance(response, dict):
        return None
    if key in response:
        return response[key]
    inner = response.get("result")
    if isinstance(inner, dict):
        if key in inner:
            return inner[key]
    return None
