# -*- coding: utf-8 -*-
"""Опциональная проба qt-mcp: агент видит и нажимает виджеты живого окна (разработка и сим-стенд).

**Зачем.** ``qt-mcp`` — отдельный MCP-сервер; чтобы он видел окно, внутри процесса ``gui`` должна работать проба
(``qt_mcp.probe.install``, JSON-RPC на localhost, по умолчанию порт 9142). Окно живёт в дочернем процессе ``gui``,
поэтому ставить пробу «в лаунчере» нельзя — только здесь, после создания ``QApplication``.

**Один путь, одни ручки.** ``QT_MCP_PROBE=1`` включает, ``QT_MCP_PORT`` задаёт порт (умолчание 9142). Это те же
имена, что читают сам ``qt_mcp`` (хук ``qt_mcp.probe._auto_hook`` и ``qt_mcp_probe.pth`` в venv) и MCP-сервер
``qt-mcp``, поэтому пара «проба и сервер» совпадает без второго набора переменных. Параллельных ручек с другими
именами нет. Значение флага сверяется дословно: ``1`` включает, пусто и ``0`` выключают, всё остальное
(``1:9142``, ``true``) — опечатка и предупреждение, а не тишина.

**Выключено по умолчанию.** Без ручки пакет ``qt_mcp`` даже не импортируется: в боевой сборке его может не быть.

**Громкость без падения.** Проба — инструмент разработки, не часть системы: любой отказ (опечатка флага, битый порт,
нет пакета, порт занят, нет ``QApplication``, исключение установки) даёт одно предупреждение и ``False``, окно
процесса ``gui`` продолжает работать. Тишины нет ни в одной из веток.

**Безопасность.** Проба — открытая дверь: без аутентификации, читает поля паролей, слушает только 127.0.0.1. Не
включать при чужих пользователях ОС и открытом недоверенном браузере. Успешная установка поэтому тоже пишется на
уровне WARNING (см. :func:`install_if_enabled`).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from multiprocess_framework.modules.logger_module import get_std_logger

ENV_PROBE = "QT_MCP_PROBE"
ENV_PORT = "QT_MCP_PORT"
DEFAULT_PORT = 9142

_LOG = get_std_logger(__name__)


def _port(env: Mapping[str, str]) -> int:
    """Порт из env; пусто — умолчание; не число или вне 1..65535 — ``ValueError`` (без отката на умолчание)."""
    raw = env.get(ENV_PORT, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise ValueError(f"{ENV_PORT}={raw!r}: ожидается целое 1..65535")
    return port


def _resolve_install() -> Callable[..., object]:
    """Реальный ``qt_mcp.probe.install``; импорт здесь, чтобы без ручки пакет не трогался."""
    from qt_mcp.probe import install

    return install


def install_if_enabled(
    env: Mapping[str, str] | None = None,
    *,
    warn: Callable[[str], None] | None = None,
    installer: Callable[..., object] | None = None,
) -> bool:
    """Поставить пробу, если включена ``QT_MCP_PROBE=1``. Вызывать после создания ``QApplication``.

    Возвращает ``True`` только когда ``install`` вернул живую пробу; любой отказ — ``False`` плюс ровно одно
    предупреждение. Всё пишется через ``warn`` (по умолчанию стандартный логгер модуля) на уровне WARNING: отказ —
    потому что проба запрошена, но не работает; успех — потому что это открытая дверь без аутентификации.

    ``installer`` — подмена ``qt_mcp.probe.install`` для тестов (настоящий возвращает ``None`` при занятом порте
    или без ``QApplication``).
    """
    env = os.environ if env is None else env
    warn = _LOG.warning if warn is None else warn

    flag = env.get(ENV_PROBE, "")
    if flag in ("", "0"):
        return False
    if flag != "1":
        warn(f"qt-mcp: {ENV_PROBE}={flag!r}: ожидается 1 (включить) либо 0 (выключить); проба не поставлена")
        return False

    try:
        port = _port(env)
    except ValueError as exc:
        warn(f"qt-mcp: {exc}, проба не поставлена")
        return False

    try:
        install = _resolve_install() if installer is None else installer
    except ImportError as exc:
        warn(f"qt-mcp: {ENV_PROBE}=1, но пакет qt_mcp не установлен ({exc}); проба не поставлена")
        return False
    except Exception as exc:
        warn(f"qt-mcp: проба не поставлена: импорт qt_mcp упал: {type(exc).__name__}: {exc}")
        return False

    try:
        probe = install(port=port)
    except Exception as exc:
        warn(f"qt-mcp: проба не поставлена: {type(exc).__name__}: {exc}")
        return False
    if probe is None:
        warn(f"qt-mcp: проба не поставлена: порт {port} занят либо нет QApplication")
        return False

    warn(
        f"qt-mcp probe installed on localhost:{port} — ОТКРЫТАЯ ДВЕРЬ: без аутентификации, "
        "читает поля паролей, слушает только 127.0.0.1"
    )
    return True


__all__ = ["DEFAULT_PORT", "ENV_PORT", "ENV_PROBE", "install_if_enabled"]
