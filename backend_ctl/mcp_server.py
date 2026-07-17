# -*- coding: utf-8 -*-
"""MCP-сервер backend_ctl — stdio JSON-RPC поверх BackendDriver (Ф1 Task 1.7, P3).

Claude (или любой MCP-клиент) запускает этот процесс и говорит с ним по stdio:
newline-delimited JSON-RPC 2.0 (initialize → notifications/initialized → tools/*).
Сервер держит один :class:`~backend_ctl.driver.BackendDriver` и лениво подключает
его к сокету живого бэкенда (`BACKEND_CTL=1`, SocketChannel в ProcessManager) при
первом вызове инструмента — бэкенд поднимается отдельно (run.py / BackendHarness).

Протокол реализован руками, без SDK: серверу нужны только initialize / tools/list /
tools/call / ping — стабильное tools-only подмножество спеки MCP (см. спеку
modelcontextprotocol, transports: stdio). Осознанный трейд-офф вместо новой
зависимости: dev-инструмент, «держать тонким» (priority_product_over_engine).

Дисциплина stdio: в stdout — ТОЛЬКО валидные MCP-сообщения, весь лог — в stderr.

Запуск: ``python -m backend_ctl.mcp_server [--host H] [--port P] [--timeout S]``
(дефолты из env BACKEND_CTL_HOST / BACKEND_CTL_PORT — те же, что у driver/harness).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Dict, Optional, TextIO

from backend_ctl.driver import BackendDriver
from backend_ctl.endpoint_config import resolve_endpoint
from backend_ctl.mcp_tools import ToolSpec, build_registry

#: Версии спеки MCP, которые сервер готов подтвердить клиенту как есть.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
#: Ответ по умолчанию, если клиент просит неизвестную версию.
DEFAULT_PROTOCOL_VERSION = "2025-06-18"

SERVER_INFO = {"name": "backend-ctl", "version": "1.0.0"}

INSTRUCTIONS = (
    "Инструменты управления живым бэкендом Inspector_bottles через backend_ctl-driver "
    "(сокет ProcessManager). Бэкенд должен быть запущен отдельно с BACKEND_CTL=1. "
    "Начинай сессию с capabilities — это «контактная книжка» системы: процессы, их "
    "команды, регистры и каналы без чтения исходников."
)

# Коды ошибок JSON-RPC 2.0.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class BackendUnavailable(RuntimeError):
    """Бэкенд недоступен (сокет не поднят/оборван) — понятный текст для агента."""


class MCPServer:
    """Tools-only MCP-сервер: маршрутизация JSON-RPC + ленивый driver.

    Транспорт (чтение/запись строк) вынесен в :meth:`serve`; вся маршрутизация —
    в чистом :meth:`handle_message` (dict → Optional[dict]), что позволяет
    тестировать протокол без процессов и сокетов.
    """

    def __init__(
        self,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        request_timeout: float = 5.0,
        driver_factory: Any = None,
        log: Any = None,
    ) -> None:
        self._host, self._port = resolve_endpoint(host, port)
        self._request_timeout = request_timeout
        # Фабрика для тестов: () → объект с интерфейсом BackendDriver (fake).
        self._driver_factory = driver_factory or self._default_driver_factory
        self._driver: Optional[BackendDriver] = None
        self._registry: Dict[str, ToolSpec] = build_registry()
        self._log = log or (lambda m: print(m, file=sys.stderr, flush=True))

    # ---- Driver lifecycle ----

    def _default_driver_factory(self) -> BackendDriver:
        drv = BackendDriver(self._host, self._port, default_timeout=self._request_timeout)
        drv.connect()
        time.sleep(0.3)  # дать SocketChannel зарегистрировать клиента (как в harness)
        return drv

    def _ensure_driver(self) -> BackendDriver:
        """Лениво подключить driver; при недоступном бэкенде — понятная ошибка."""
        if self._driver is None:
            try:
                self._driver = self._driver_factory()
            except OSError as exc:
                raise BackendUnavailable(
                    f"бэкенд недоступен на {self._host}:{self._port} ({exc}). "
                    "Подними систему с BACKEND_CTL=1 (например `python multiprocess_prototype/run.py` "
                    "или BackendHarness) и повтори вызов."
                ) from exc
        return self._driver

    def _reset_driver(self) -> None:
        """Сбросить соединение (следующий вызов переподключится)."""
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:  # noqa: BLE001 — сброс не должен падать
                pass
            self._driver = None

    def close(self) -> None:
        self._reset_driver()

    # ---- Маршрутизация JSON-RPC (чистая, тестируемая) ----

    def handle_message(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Обработать одно входящее сообщение. None = ответа нет (notification)."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._error(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, "не JSON-RPC 2.0")

        method = msg.get("method")
        msg_id = msg.get("id")

        # Notifications (нет id) — молча принимаем известные и неизвестные.
        if msg_id is None:
            return None

        if method == "initialize":
            return self._result(msg_id, self._initialize(msg.get("params") or {}))
        if method == "ping":
            return self._result(msg_id, {})
        if method == "tools/list":
            return self._result(msg_id, {"tools": [s.to_mcp() for s in self._registry.values()]})
        if method == "tools/call":
            return self._tools_call(msg_id, msg.get("params") or {})
        return self._error(msg_id, METHOD_NOT_FOUND, f"метод не поддерживается: {method!r}")

    def _initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else DEFAULT_PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": dict(SERVER_INFO),
            "instructions": INSTRUCTIONS,
        }

    def _tools_call(self, msg_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        spec = self._registry.get(name or "")
        if spec is None:
            return self._error(msg_id, INVALID_PARAMS, f"неизвестный инструмент: {name!r}")
        arguments = params.get("arguments") or {}
        try:
            driver = self._ensure_driver()
            result = spec.handler(driver, arguments)
        except BackendUnavailable as exc:
            self._reset_driver()
            return self._tool_error(msg_id, str(exc))
        except OSError as exc:
            # Соединение оборвалось по ходу вызова — сбросить, чтобы следующий переподключился.
            self._reset_driver()
            return self._tool_error(msg_id, f"соединение с бэкендом оборвано: {exc}")
        except Exception as exc:  # noqa: BLE001 — ошибка инструмента ≠ ошибка протокола
            return self._tool_error(msg_id, f"{type(exc).__name__}: {exc}")
        text = json.dumps(result, ensure_ascii=False, default=str)
        return self._result(msg_id, {"content": [{"type": "text", "text": text}], "isError": False})

    # ---- Формы ответов ----

    @staticmethod
    def _result(msg_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}

    @classmethod
    def _tool_error(cls, msg_id: Any, text: str) -> Dict[str, Any]:
        """Ошибка исполнения инструмента — result с isError (по спеке НЕ protocol-error)."""
        return cls._result(msg_id, {"content": [{"type": "text", "text": text}], "isError": True})

    # ---- stdio-цикл ----

    def serve(self, stdin: TextIO, stdout: TextIO) -> None:
        """Читать newline-delimited JSON-RPC из stdin, отвечать в stdout (до EOF)."""
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self._write(stdout, self._error(None, PARSE_ERROR, "невалидный JSON"))
                continue
            try:
                response = self.handle_message(msg)
            except Exception as exc:  # noqa: BLE001 — цикл сервера не должен умирать
                self._log(f"[mcp_server] handle_message бросил {exc!r}")
                response = self._error(msg.get("id") if isinstance(msg, dict) else None, INVALID_REQUEST, str(exc))
            if response is not None:
                self._write(stdout, response)
        self.close()

    @staticmethod
    def _write(stdout: TextIO, message: Dict[str, Any]) -> None:
        stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
        stdout.flush()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="MCP-сервер backend_ctl (stdio)")
    parser.add_argument("--host", default=None, help="host endpoint'a; None -> env BACKEND_CTL_HOST -> 127.0.0.1")
    parser.add_argument("--port", type=int, default=None, help="port endpoint'a; None -> env BACKEND_CTL_PORT")
    parser.add_argument("--timeout", type=float, default=5.0, help="таймаут ответа бэкенда, сек")
    args = parser.parse_args(argv)

    host, port = resolve_endpoint(args.host, args.port)
    server = MCPServer(host=host, port=port, request_timeout=args.timeout)
    print(f"[mcp_server] backend-ctl MCP на stdio; бэкенд {host}:{port}", file=sys.stderr, flush=True)
    try:
        server.serve(sys.stdin, sys.stdout)
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
