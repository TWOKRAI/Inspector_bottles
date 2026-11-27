"""Разбор ответа ``request_command`` — один для всех вкладок устройств."""

from __future__ import annotations

from typing import Any

# Ключи «короткой» обёртки: ответ с ними разворачивается, даже если рядом лежит ``status``.
_WRAPPER_KEYS = {"result", "status", "request_id", "command"}


def unwrap_reply(response: Any) -> dict:
    """Достать ответ обработчика из ответа команды.

    Настоящий ответ идёт в конверте роутера (``RouterManager.reply_to_request``):
    ``{type, command, sender, targets, queue_type, request_id, success, result}``.

    Args:
        response: конверт, короткая обёртка ``{"result": {...}}`` или сам ответ.

    Returns:
        ``result``, если это dict и перед нами обёртка; иначе ``response`` без изменений
        (так отказ с ``result=None`` сохраняет ``success``); не dict -> ``{}``.
    """
    if not isinstance(response, dict):
        return {}
    inner = response.get("result")
    if isinstance(inner, dict) and ("status" not in response or set(response) <= _WRAPPER_KEYS):
        return inner
    return response
