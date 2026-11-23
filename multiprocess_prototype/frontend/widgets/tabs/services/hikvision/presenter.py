# -*- coding: utf-8 -*-
"""HikvisionSettingsPresenter — логика секции «Hikvision камера» (без Qt-виджетов).

Команды плагина ``hikvision`` (плагин на ядре ``camera_device``):
  - fire-and-forget: ``take_device`` / ``release_device`` — через
    ``topology_bridge.on_action_command``; правка поля — ``register_update``
    ``{register, field, value}`` через ``CommandSender.send_command`` (как live field-write
    инспектора Pipeline);
  - request/response: ``list_devices`` / ``read_params`` — через
    ``CommandSender.request_command`` на worker-потоке (``RequestRunner``), результат
    доставляется в main-thread.

Изображение идёт в дисплей активного рецепта — секция только управляет камерой.
Выбор прибора — поля register'а плагина (``device_select``, ``device_serial``, …) в инспекторе.
"""

from __future__ import annotations

from typing import Any, Callable

from multiprocess_framework.modules.logger_module import get_std_logger

logger = get_std_logger(__name__)

_PLUGIN = "hikvision"

NO_LIVE_HINT = (
    "Команда не отправлена: нет запущенного процесса камеры Hikvision. Активируйте рецепт с камерой hikvision."
)


class HikvisionSettingsPresenter:
    """Презентер камеры Hikvision: live-команды + request/response.

    Зависимости (duck-typed, любая может быть None → graceful degradation):
        bridge          — TopologyBridge.on_action_command(plugin, cmd, args).
        topology        — TopologyRepository.load().to_dict() (поиск процесса камеры).
        command_sender  — CommandSender.send_command / request_command(process, cmd, args).
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

    def take_device(self) -> bool:
        """Взять прибор, выбранный в register'е плагина, и начать захват."""
        return self._send("take_device", {})

    def release_device(self) -> bool:
        """Остановить захват и отпустить прибор."""
        return self._send("release_device", {})

    def _send(self, command: str, args: dict) -> bool:
        if self._bridge is None:
            logger.debug("Hikvision: bridge недоступен — %s пропущена", command)
            return False
        try:
            return bool(self._bridge.on_action_command(_PLUGIN, command, args))
        except Exception as exc:
            logger.warning("Hikvision: команда %s провалилась: %s", command, exc)
            return False

    def set_parameters(self, fps: float, exposure: float, gain: float) -> tuple[bool, list[str]]:
        """Правка полей register'а плагина: ``register_update`` на каждое валидное поле.

        ``frame_rate`` уходит только при fps > 0 (пустое поле = 0.0, min register'а 1.0); ``exposure_time`` и
        ``gain`` — как есть (gain 0.0 валиден). Возвращает ``(отправлено, имена_пропущенных_полей)``.
        """
        proc = self.hikvision_process_name()
        if self._sender is None or proc is None:
            logger.debug("Hikvision: register_update недоступен (нет sender/процесса)")
            return False, []
        skipped = [] if fps > 0 else ["frame_rate"]
        fields = (("frame_rate", fps), ("exposure_time", exposure), ("gain", gain))
        try:
            for field, value in fields:
                if field in skipped:
                    continue
                self._sender.send_command(
                    proc, "register_update", {"register": _PLUGIN, "field": field, "value": float(value)}
                )
        except Exception as exc:
            logger.warning("Hikvision: register_update провалился: %s", exc)
            return False, []
        return True, skipped

    # --- request/response команды (результат в main-thread) ---

    def list_devices(self, on_result: Callable[[list[dict], str], None]) -> None:
        """Запросить приборы; ``on_result(devices, error)`` в main-thread (``error`` пуст при успехе)."""

        def _done(response: Any) -> None:
            body, error = _split(response)
            on_result(body.get("devices") or [], error)

        self._request("list_devices", {}, _done)

    def read_params(self, on_result: Callable[[dict, dict, str], None]) -> None:
        """Запросить снимок параметров; ``on_result(params, param_errors, error)`` в main-thread."""

        def _done(response: Any) -> None:
            body, error = _split(response)
            on_result(body.get("params") or {}, body.get("param_errors") or {}, error)

        self._request("read_params", {}, _done)

    def _request(self, command: str, args: dict, cb: Callable[[Any], None]) -> None:
        proc = self.hikvision_process_name()
        if self._sender is None or self._runner is None or proc is None:
            logger.debug("Hikvision: request %s недоступен (нет sender/runner/процесса)", command)
            cb({"success": False, "error": NO_LIVE_HINT})
            return
        self._runner.submit(
            lambda: self._sender.request_command(proc, command, args),
            on_result=cb,
        )


def _split(response: Any) -> tuple[dict, str]:
    """Тело ответа и текст отказа (``""`` при успехе).

    Ответ плагина — ``{"success": bool, ..., "error": str}``; ядро на неизвестную команду отвечает
    ``{"status": "error", "reason": "No handler for key '<имя>'"}``. Тело может быть вложено в ``result``.
    """
    if not isinstance(response, dict):
        return {}, "Нет ответа процесса камеры."
    inner = response.get("result")
    body = inner if isinstance(inner, dict) else response
    for layer in (response, body):
        if layer.get("success") is False or layer.get("status") == "error":
            return body, str(layer.get("error") or layer.get("reason") or "Команда отклонена.")
    return body, ""
