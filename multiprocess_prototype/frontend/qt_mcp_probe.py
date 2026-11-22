# -*- coding: utf-8 -*-
"""Опциональная проба qt-mcp: агент видит и нажимает виджеты живого окна (разработка и сим-стенд).

**Зачем.** ``qt-mcp`` — отдельный MCP-сервер; чтобы он видел окно, внутри процесса ``gui`` должна работать проба
(``qt_mcp.probe.install``, JSON-RPC на localhost, по умолчанию порт 9142). Окно живёт в дочернем процессе ``gui``,
поэтому ставить пробу «в лаунчере» нельзя — только здесь, после создания ``QApplication``.

**Выключено по умолчанию.** Ручка — env ``INSPECTOR_QT_MCP_PROBE=1`` (порт — ``INSPECTOR_QT_MCP_PORT``, умолчание
9142). Без ручки пакет ``qt_mcp`` даже не импортируется: в боевой сборке его может не быть. Если ручка включена, а пакета
нет, это не падение приложения, а предупреждение в лог и ``False``: проба — инструмент разработки, не часть системы.
Проба слушает только 127.0.0.1 (так устроен сам ``qt_mcp``).
"""

from __future__ import annotations

import os
from typing import Any, Callable, Mapping, Optional

ENV_PROBE = "INSPECTOR_QT_MCP_PROBE"
ENV_PORT = "INSPECTOR_QT_MCP_PORT"
DEFAULT_PORT = 9142


def _port(env: Mapping[str, str]) -> int:
    """Порт из env; не число или вне 1..65535 — ошибка настройки, молчаливого умолчания нет."""
    raw = env.get(ENV_PORT, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f"{ENV_PORT}={raw!r}: ожидается целое число") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{ENV_PORT}={port}: порт вне 1..65535")
    return port


def install_if_enabled(
    env: Optional[Mapping[str, str]] = None,
    *,
    log: Optional[Callable[..., None]] = None,
    installer: Optional[Callable[..., Any]] = None,
) -> bool:
    """Поставить пробу, если включена ``INSPECTOR_QT_MCP_PROBE=1``. Вызывать после создания ``QApplication``.

    Возвращает ``True`` только когда проба поставлена. ``installer`` — подмена ``qt_mcp.probe.install`` для тестов.
    """
    env = os.environ if env is None else env
    if env.get(ENV_PROBE, "").strip() != "1":
        return False
    port = _port(env)
    if installer is None:
        try:
            from qt_mcp.probe import install as installer
        except ImportError as exc:
            if log is not None:
                log(f"qt-mcp: {ENV_PROBE}=1, но пакет qt_mcp не установлен ({exc}); проба не поставлена")
            return False
    installer(port=port)
    if log is not None:
        log(f"qt-mcp: проба поставлена, 127.0.0.1:{port}")
    return True


__all__ = ["DEFAULT_PORT", "ENV_PORT", "ENV_PROBE", "install_if_enabled"]
