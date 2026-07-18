# -*- coding: utf-8 -*-
"""mcp_errors.py — «ошибки, которые учат» для MCP-сервера backend_ctl (Task 3.3).

Чистые построители текста ошибок (без зависимости от SDK — тестируются отдельно).
Идея: отказ должен называть ВАЛИДНЫЕ альтернативы, а не просто «нет такого».
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable


def suggest_tools(name: str, known: Iterable[str], *, limit: int = 3) -> list[str]:
    """Ближайшие по написанию имена инструментов (опечатки/забытый суффикс)."""
    return difflib.get_close_matches(name, list(known), n=limit, cutoff=0.5)


def unknown_tool_error(name: str, known: Iterable[str]) -> str:
    """Неизвестный инструмент → назвать ближайшие + подсказать tools/list."""
    sugg = suggest_tools(name, known)
    hint = f" Возможно, вы имели в виду: {', '.join(sugg)}." if sugg else ""
    return f"неизвестный инструмент {name!r}.{hint} Полный каталог — вызов tools/list."


def blocked_tool_error(name: str, mode: str, allowed_names: Iterable[str]) -> str:
    """Инструмент заблокирован safety-режимом → назвать доступные."""
    allowed = ", ".join(sorted(allowed_names))
    return (
        f"инструмент {name!r} заблокирован режимом сервера '{mode}'. "
        f"Доступные инструменты: {allowed}. "
        f"Перезапусти MCP-сервер без ограничивающего флага, если нужна запись."
    )


def read_only_command_blocked_error(command: str) -> str:
    """send_command с не-read командой в read-only → назвать разрешённые префиксы."""
    return (
        f"send_command({command!r}) заблокирован в режиме read-only: через него разрешены "
        f"только read-команды (introspect.* / state.get*). Для записи запусти сервер без --read-only."
    )


__all__ = [
    "suggest_tools",
    "unknown_tool_error",
    "blocked_tool_error",
    "read_only_command_blocked_error",
]
