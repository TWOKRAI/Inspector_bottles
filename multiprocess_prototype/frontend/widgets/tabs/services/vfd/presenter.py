# -*- coding: utf-8 -*-
"""VfdPresenter — логика секции «ПЧ» (без Qt-виджетов).

Все команды идут в процесс ``devices`` через RequestRunner.
Имена команд — из DeviceHubPlugin.commands (Р7).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TARGET = "devices"


class VfdPresenter:
    """Презентер ПЧ: команды vfd_* + describe + статус.

    Зависимости (duck-typed):
        command_sender  — CommandSender.request_command(process, cmd, args).
        request_runner  — RequestRunner.submit(fn, on_result).
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
    # Управление ПЧ (request/response через RequestRunner)
    # ------------------------------------------------------------------ #

    def vfd_run(
        self,
        device_id: str,
        freq_hz: float,
        reverse: bool = False,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Пуск ПЧ."""
        self._request(
            "vfd_run",
            {"device_id": device_id, "freq_hz": float(freq_hz), "direction": 1 if reverse else 0},
            on_result or (lambda _: None),
        )

    def vfd_set_freq(
        self,
        device_id: str,
        freq_hz: float,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Сменить частоту на ходу."""
        self._request(
            "vfd_set_freq",
            {"device_id": device_id, "freq_hz": float(freq_hz)},
            on_result or (lambda _: None),
        )

    def vfd_stop(
        self,
        device_id: str,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Остановить ПЧ."""
        self._request("vfd_stop", {"device_id": device_id}, on_result or (lambda _: None))

    def vfd_reset_fault(
        self,
        device_id: str,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Сброс аварии."""
        self._request("vfd_reset_fault", {"device_id": device_id}, on_result or (lambda _: None))

    def vfd_get_status(
        self,
        device_id: str,
        on_result: Callable[[dict], None],
    ) -> None:
        """Форс-запрос статуса ПЧ."""
        self._request(
            "vfd_get_status",
            {"device_id": device_id},
            lambda r: on_result(_extract_top(r)),
        )

    def device_describe(
        self,
        device_id: str,
        on_result: Callable[[dict], None],
    ) -> None:
        """Описание устройства (meta для лимитов частоты + mode носителя)."""
        self._request(
            "device_describe",
            {"device_id": device_id},
            lambda r: on_result(_extract_top(r)),
        )

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _request(self, command: str, args: dict, cb: Callable[[dict], None]) -> None:
        if self._sender is None or self._runner is None:
            logger.debug("VFD: request %s недоступен (нет sender/runner)", command)
            cb({})
            return
        self._runner.submit(
            lambda: self._sender.request_command(_TARGET, command, args),
            on_result=cb,
        )


def _extract_top(response: Any) -> dict:
    """Развернуть ответ: {...} или {"result": {...}}."""
    if not isinstance(response, dict):
        return {}
    inner = response.get("result")
    if isinstance(inner, dict) and set(response) <= {"result", "status", "request_id", "command"}:
        return inner
    return response
