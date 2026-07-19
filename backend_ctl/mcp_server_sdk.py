# -*- coding: utf-8 -*-
"""mcp_server_sdk.py — MCP-сервер backend_ctl на официальном SDK (пакет ``mcp``).

Тот же реестр инструментов (:mod:`backend_ctl.mcp_tools`) и тот же жизненный цикл
driver'а (:class:`~backend_ctl.mcp_driver_session.DriverSession`), что и у
рукописного сервера, но транспорт/протокол — низкоуровневый ``mcp.server.lowlevel``
поверх stdio (Task 3.1). За реестром: смена стека = один файл, имена инструментов
и семантика НЕ меняются.

Что даёт SDK-слой поверх рукописного:
  * tool-annotations (readOnlyHint/destructiveHint/idempotentHint) — из класса
    безопасности инструмента (Task 3.1/3.2);
  * safety-режимы ``--read-only`` / ``--disable-destructive`` — enforce на сервере
    ДО вызова driver'а; ограниченный режим скрывает недоступные инструменты из
    tools/list (Task 3.2);
  * actionable-ошибки — неизвестный инструмент называет ближайшие имена, блок
    режимом называет доступные (:mod:`backend_ctl.mcp_errors`, Task 3.3).

Зависимость ``mcp`` — опциональная (extra ``ctl``). Модуль импортируется без неё;
:func:`build_server`/:func:`main` дают понятную ошибку с командой установки.

Запуск: ``python -m backend_ctl.mcp_server_sdk [--read-only | --disable-destructive]``
(дефолты host/port — из env BACKEND_CTL_HOST/PORT, как у driver/harness).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional

from backend_ctl import mcp_errors
from backend_ctl.endpoint_config import resolve_endpoint
from backend_ctl.mcp_driver_session import BackendUnavailable, DriverSession
from backend_ctl.mcp_tools import (
    MODE_FULL,
    MODE_NO_DESTRUCTIVE,
    MODE_READ_ONLY,
    build_registry,
    is_command_read_safe,
    is_tool_allowed,
    tool_annotations,
)

SERVER_NAME = "backend-ctl"
SERVER_VERSION = "2.0.0"  # 2.x — реализация на официальном SDK (1.x — рукописная)
INSTRUCTIONS = (
    "Инструменты управления живым бэкендом Inspector_bottles через backend_ctl-driver "
    "(сокет ProcessManager). Бэкенд должен быть запущен отдельно с BACKEND_CTL=1. "
    "Начинай сессию с capabilities — это «контактная книжка» системы: процессы, их "
    "команды, регистры и каналы без чтения исходников."
)

#: env-переменная выбора safety-режима (альтернатива argv-флагам).
MODE_ENV_VAR = "BACKEND_CTL_MCP_MODE"

_INSTALL_HINT = "pip install 'inspector-bottles[ctl]'  (или: pip install 'mcp>=1.27,<1.28')"


class MCPNotInstalled(RuntimeError):
    """Пакет ``mcp`` (extra ``ctl``) не установлен — понятный текст с командой установки."""


def _require_mcp():
    """Лениво импортировать SDK; при отсутствии — :class:`MCPNotInstalled` с командой установки."""
    try:
        import mcp.types as mcp_types  # noqa: PLC0415 — ленивый импорт опционального extra
        from mcp.server.lowlevel import Server  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover — путь без установленного extra
        raise MCPNotInstalled(
            f"MCP-сервер на SDK требует пакет 'mcp' (extra 'ctl'), он не установлен. Установи: {_INSTALL_HINT}"
        ) from exc
    return mcp_types, Server


def resolve_mode(
    *, read_only: bool = False, disable_destructive: bool = False, env: Optional[Dict[str, str]] = None
) -> str:
    """Определить safety-режим: argv-флаги > env BACKEND_CTL_MCP_MODE > full.

    ``--read-only`` и ``--disable-destructive`` — взаимоисключающие (read-only строже).
    """
    if read_only:
        return MODE_READ_ONLY
    if disable_destructive:
        return MODE_NO_DESTRUCTIVE
    env = env if env is not None else os.environ
    env_mode = env.get(MODE_ENV_VAR)
    if env_mode in (MODE_FULL, MODE_READ_ONLY, MODE_NO_DESTRUCTIVE):
        return env_mode
    return MODE_FULL


class SDKToolServer:
    """Адаптер реестра ToolSpec под low-level MCP Server: list_tools + call_tool.

    Держит :class:`DriverSession` (lazy-connect/reconnect/replay/watch-resume) и
    применяет safety-режим и actionable-ошибки. Логику инструментов не дублирует —
    зовёт handler'ы реестра, как рукописный сервер.
    """

    def __init__(
        self,
        *,
        mode: str = MODE_FULL,
        host: Optional[str] = None,
        port: Optional[int] = None,
        request_timeout: float = 5.0,
        driver_factory: Any = None,
        log: Any = None,
    ) -> None:
        self._mode = mode
        self._log = log or (lambda m: print(m, file=sys.stderr, flush=True))
        self._session = DriverSession(
            host=host, port=port, request_timeout=request_timeout, driver_factory=driver_factory, log=self._log
        )
        self._registry = build_registry()

    @property
    def mode(self) -> str:
        return self._mode

    def close(self) -> None:
        self._session.close()

    def close_graceful(self) -> None:
        """Закрыть сессию, сняв durable-подписки на бэкенде (D.2 §5.2, долг D.1 §12).

        Единая точка cleanup из lifespan для ВСЕХ путей завершения MCP-сессии
        (DELETE / idle-timeout / крэш). Step 2 — пока обычный ``close()``; реальный
        graceful-unsubscribe (обход registry → снимающие команды, пока сокет жив)
        придёт в Step 5. Держит стабильную сигнатуру вызова через все шаги.
        """
        self.close()

    def _allowed_names(self) -> List[str]:
        """Имена инструментов, доступных в текущем режиме (для tools/list и подсказок)."""
        return [name for name in self._registry if is_tool_allowed(name, self._mode)]

    # ---- Реализация протокольных операций (чистые, тестируются без транспорта) ----

    def list_tools(self) -> List[Any]:
        """types.Tool со схемой + annotations; в ограниченном режиме недоступные скрыты."""
        mcp_types, _ = _require_mcp()
        tools: List[Any] = []
        for name, spec in self._registry.items():
            if not is_tool_allowed(name, self._mode):
                continue  # скрыть недоступные в ограниченном режиме (Task 3.2)
            tools.append(
                mcp_types.Tool(
                    name=spec.name,
                    description=spec.description,
                    inputSchema=spec.input_schema,
                    annotations=mcp_types.ToolAnnotations(**tool_annotations(name)),
                )
            )
        return tools

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]]) -> Any:
        """Диспатч одного инструмента с safety-гейтом и actionable-ошибками.

        Возвращает ``types.CallToolResult`` (isError на ошибке/блоке) или список
        ``types.TextContent`` (успех). Гейт применяется ДО подключения driver'а.
        """
        mcp_types, _ = _require_mcp()
        arguments = arguments or {}

        spec = self._registry.get(name)
        if spec is None:
            return self._error(mcp_types, mcp_errors.unknown_tool_error(name, self._registry.keys()))

        # Safety-режим: блок недоступного инструмента ДО driver'а (annotations — лишь hints).
        if not is_tool_allowed(name, self._mode):
            return self._error(mcp_types, mcp_errors.blocked_tool_error(name, self._mode, self._allowed_names()))
        # Ограниченный режим: send_command пропускает только read-команды (introspect.* / state.get*).
        if self._mode in (MODE_READ_ONLY, MODE_NO_DESTRUCTIVE) and name == "send_command":
            command = str(arguments.get("command") or "")
            if not is_command_read_safe(command):
                return self._error(mcp_types, mcp_errors.restricted_command_blocked_error(command))

        try:
            driver = self._session.ensure()
            result = spec.handler(driver, arguments)
        except BackendUnavailable as exc:
            self._session.reset()
            return self._error(mcp_types, str(exc))
        except OSError as exc:
            self._session.reset()
            return self._error(mcp_types, f"соединение с бэкендом оборвано: {exc}")
        except Exception as exc:  # noqa: BLE001 — ошибка инструмента ≠ ошибка протокола
            return self._error(mcp_types, f"{type(exc).__name__}: {exc}")

        # Однократный отчёт о реконнекте — в этот ответ (агент знает: подписки replay'нуты).
        reconnect_report = self._session.pop_reconnect_report()
        if reconnect_report is not None and isinstance(result, dict):
            result = {**result, **reconnect_report}
        text = json.dumps(result, ensure_ascii=False, default=str)
        return [mcp_types.TextContent(type="text", text=text)]

    @staticmethod
    def _error(mcp_types, message: str) -> Any:
        """Ошибка инструмента как CallToolResult(isError=True) — по спеке НЕ protocol-error."""
        return mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text=message)],
            isError=True,
        )


def _as_tool_server_factory(spec: Any) -> Callable[[], SDKToolServer]:
    """Нормализовать вход :func:`build_server` в фабрику per-session ``SDKToolServer``.

    * инстанс ``SDKToolServer`` → фабрика, возвращающая ЕГО ЖЕ (stdio / тесты: одна
      сессия на процесс, back-compat);
    * zero-arg callable → сама фабрика (HTTP-мультиклиент: свежий ``SDKToolServer`` —
      свой ``DriverSession`` → сокет → ``session``-uuid → dotted-subscriber — на КАЖДУЮ
      MCP-сессию, изоляция поверх D.1a).
    """
    if isinstance(spec, SDKToolServer):
        return lambda: spec
    if callable(spec):
        return spec
    raise TypeError(f"build_server ждёт SDKToolServer или zero-arg фабрику, получено {type(spec).__name__}")


def build_server(tool_server_or_factory: Any):
    """Собрать low-level MCP Server с per-session lifespan (D.2, Вариант B).

    ``tool_server_or_factory`` — инстанс :class:`SDKToolServer` (один на процесс:
    stdio, тесты) ИЛИ zero-arg фабрика (свежий per MCP-сессию — HTTP-мультиклиент).
    lifespan создаёт tool_server на ВХОД каждой MCP-сессии и гарантированно закрывает
    его на ВЫХОДЕ (DELETE / idle-timeout / крэш — все пути завершения сессии в
    stateful-менеджере SDK): здесь закрывается долг D.1 §12 (осиротевшие подписки).
    Хендлеры берут свой tool_server из ``request_context.lifespan_context`` — состояние
    реестра/driver'а изолировано между сессиями.
    """
    _, Server = _require_mcp()
    factory = _as_tool_server_factory(tool_server_or_factory)

    @asynccontextmanager
    async def _session_lifespan(_server):  # noqa: D401 — фабрика per-session контекста
        ts = factory()
        try:
            yield ts
        finally:
            # Cleanup осиротевших подписок (долг D.1 §12). SYNC, без await: idle-reap
            # завершает сессию отменой cancel-scope, где await недопустим (§5.2). Step 5
            # наполнит close_graceful реальным unsubscribe; здесь — обычный close.
            # Best-effort: бэкенд мог умереть — не роняем shutdown сессии.
            try:
                ts.close_graceful()
            except Exception:  # noqa: BLE001 — cleanup не роняет завершение сессии
                pass

    server = Server(SERVER_NAME, version=SERVER_VERSION, instructions=INSTRUCTIONS, lifespan=_session_lifespan)

    @server.list_tools()
    async def _handle_list_tools():  # noqa: D401 — SDK-хендлер
        return server.request_context.lifespan_context.list_tools()

    @server.call_tool()
    async def _handle_call_tool(name: str, arguments: Optional[Dict[str, Any]]):  # noqa: D401
        return server.request_context.lifespan_context.call_tool(name, arguments)

    return server


async def _run(tool_server: SDKToolServer) -> None:
    """Поднять сервер на stdio до EOF."""
    import mcp.server.stdio as mcp_stdio  # noqa: PLC0415 — ленивый импорт опционального extra

    server = build_server(tool_server)
    async with mcp_stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="MCP-сервер backend_ctl на официальном SDK (stdio)")
    parser.add_argument("--host", default=None, help="host endpoint'a; None -> env BACKEND_CTL_HOST -> 127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="port endpoint'a; None -> env BACKEND_CTL_PORT")
    parser.add_argument("--timeout", type=float, default=5.0, help="таймаут ответа бэкенда, сек")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--read-only", action="store_true", help="только read+subscribe (write/escalated блок)")
    mode_group.add_argument(
        "--disable-destructive",
        action="store_true",
        help="блок разрушающих (write/escalated); read+subscribe разрешены",
    )
    args = parser.parse_args(argv)

    try:
        _require_mcp()
    except MCPNotInstalled as exc:
        print(f"[mcp_server_sdk] {exc}", file=sys.stderr, flush=True)
        return 2

    import asyncio  # noqa: PLC0415 — нужен только при реальном запуске

    mode = resolve_mode(read_only=args.read_only, disable_destructive=args.disable_destructive)
    host, port = resolve_endpoint(args.host, args.port)
    tool_server = SDKToolServer(mode=mode, host=host, port=port, request_timeout=args.timeout)
    print(
        f"[mcp_server_sdk] backend-ctl MCP (SDK) на stdio; бэкенд {host}:{port}; режим={mode}",
        file=sys.stderr,
        flush=True,
    )
    try:
        asyncio.run(_run(tool_server))
    except KeyboardInterrupt:
        pass
    finally:
        tool_server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
