# -*- coding: utf-8 -*-
"""DevicesPresenter — логика CRUD устройств (без Qt-виджетов).

Все команды идут в процесс ``devices`` (always-on) через
``command_sender.request_command`` на worker-потоке (``RequestRunner``).
Результат доставляется в main-thread через callback.

Паттерн: по образцу hikvision/presenter.py (duck-typed зависимости).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TARGET = "devices"


class DevicesPresenter:
    """Презентер CRUD устройств: запросы к процессу ``devices``.

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
    # Реестр
    # ------------------------------------------------------------------ #

    def device_list(
        self,
        on_result: Callable[[list[dict]], None],
        *,
        kind: str | None = None,
    ) -> None:
        """Список устройств реестра (опц. фильтр по kind). Результат в main-thread."""

        def _handle(resp: dict) -> None:
            devices = _extract(resp, "devices") or []
            if kind:
                devices = [d for d in devices if d.get("kind") == kind]
            on_result(devices)

        self._request("device_list", {}, _handle)

    def device_describe(
        self,
        device_id: str,
        on_result: Callable[[dict], None],
    ) -> None:
        """Описание устройства: entry + protocol meta + conn + stats."""
        self._request(
            "device_describe",
            {"device_id": device_id},
            lambda r: on_result(_extract_top(r)),
        )

    def device_upsert(
        self,
        entry: dict,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Создать/обновить устройство."""
        self._request(
            "device_upsert",
            entry,
            on_result or (lambda _: None),
        )

    def device_remove(
        self,
        device_id: str,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Удалить устройство из реестра."""
        self._request(
            "device_remove",
            {"device_id": device_id},
            on_result or (lambda _: None),
        )

    def device_protocols(
        self,
        kind: str | None,
        on_result: Callable[[list[dict]], None],
    ) -> None:
        """Список доступных протоколов (по kind)."""
        args: dict[str, Any] = {}
        if kind:
            args["kind"] = kind
        self._request(
            "device_protocols",
            args,
            lambda r: on_result(_extract(r, "protocols") or []),
        )

    # ------------------------------------------------------------------ #
    # Соединение
    # ------------------------------------------------------------------ #

    def device_connect(
        self,
        device_id: str,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Асинхронный connect (ответ сразу, TCP в supervisor)."""
        self._request(
            "device_connect",
            {"device_id": device_id},
            on_result or (lambda _: None),
        )

    def device_disconnect(
        self,
        device_id: str,
        on_result: Callable[[dict], None] | None = None,
    ) -> None:
        """Асинхронный disconnect."""
        self._request(
            "device_disconnect",
            {"device_id": device_id},
            on_result or (lambda _: None),
        )

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _request(self, command: str, args: dict, cb: Callable[[dict], None]) -> None:
        if self._sender is None or self._runner is None:
            logger.debug("Devices: request %s недоступен (нет sender/runner)", command)
            cb({})
            return
        self._runner.submit(
            lambda: self._sender.request_command(_TARGET, command, args),
            on_result=cb,
        )


def _extract(response: Any, key: str) -> Any:
    """Достать ``key`` из ответа request_command (возможно обёрнутого)."""
    if not isinstance(response, dict):
        return None
    if key in response:
        return response[key]
    inner = response.get("result")
    if isinstance(inner, dict) and key in inner:
        return inner[key]
    return None


def _extract_top(response: Any) -> dict:
    """Развернуть ответ: {...} или {"result": {...}}."""
    if not isinstance(response, dict):
        return {}
    inner = response.get("result")
    if isinstance(inner, dict) and set(response) <= {"result", "status", "request_id", "command"}:
        return inner
    return response
