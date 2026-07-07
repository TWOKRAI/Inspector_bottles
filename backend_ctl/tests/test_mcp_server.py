# -*- coding: utf-8 -*-
"""Тесты MCP-сервера backend_ctl (Ф1 Task 1.7, P3).

Юниты: реестр инструментов (схемы), маршрутизация JSON-RPC (initialize/ping/
tools/list/tools/call) на fake-driver — без процессов и сокетов. Live
(harness_smoke): настоящий subprocess `python -m backend_ctl.mcp_server` по stdio
против живого headless-бэкенда — тот же путь, каким сервер зовёт Claude
(acceptance 1.7: «Claude вызывает против живого бэкенда»).
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from backend_ctl.driver import Capabilities, ProcessCapabilities
from backend_ctl.mcp_server import (
    DEFAULT_PROTOCOL_VERSION,
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    MCPServer,
)
from backend_ctl.mcp_tools import MAX_EVENTS_TIMEOUT, TOOLS, build_registry


class FakeDriver:
    """Запоминает вызовы, отвечает JSON-совместимыми заглушками (без транспорта)."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, tuple, dict]] = []

    def _record(self, name: str, args: tuple, kwargs: dict) -> Dict[str, Any]:
        self.calls.append((name, args, kwargs))
        return {"success": True, "method": name}

    def __getattr__(self, name: str):
        def _method(*args: Any, **kwargs: Any) -> Any:
            if name == "capabilities":
                self.calls.append((name, args, kwargs))
                return Capabilities(
                    ok=True,
                    processes={"ProcessManager": ProcessCapabilities(True, "ProcessManager", [], [], {})},
                    topology={"preprocessor": {"class": "x.Y"}},
                    channels=[],
                )
            if name == "events":
                self.calls.append((name, args, kwargs))
                return [{"command": "state.changed"}]
            return self._record(name, args, kwargs)

        return _method

    def close(self) -> None:  # driver-интерфейс для _reset_driver
        self.calls.append(("close", (), {}))


def make_server(factory=None) -> Tuple[MCPServer, FakeDriver]:
    fake = FakeDriver()
    server = MCPServer(driver_factory=factory or (lambda: fake), log=lambda m: None)
    return server, fake


def call(server: MCPServer, method: str, params: Optional[dict] = None, msg_id: Any = 1) -> Optional[dict]:
    msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if msg_id is not None:
        msg["id"] = msg_id
    if params is not None:
        msg["params"] = params
    return server.handle_message(msg)


def tool_result(response: dict) -> Any:
    """Достать полезную нагрузку tools/call (парсит text-контент)."""
    content = response["result"]["content"]
    assert content and content[0]["type"] == "text"
    return json.loads(content[0]["text"])


# ---------------------------------------------------------------------------
# Реестр инструментов
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_names_unique_and_schemas_wellformed(self) -> None:
        registry = build_registry()
        assert len(registry) == len(TOOLS)
        for spec in TOOLS:
            schema = spec.input_schema
            assert schema["type"] == "object", spec.name
            assert isinstance(schema["properties"], dict), spec.name
            for req in schema.get("required", []):
                assert req in schema["properties"], f"{spec.name}: required {req!r} не описан"
            assert spec.description, spec.name

    def test_expected_tool_set(self) -> None:
        names = {s.name for s in TOOLS}
        # Минимальный набор P3 из плана + observability Ф1.4/1.5 + state/events (1.1).
        expected = {
            "capabilities", "get_status", "introspect_handlers", "introspect_registers",
            "introspect_router_stats", "introspect_queues", "introspect_plugins",
            "send_command", "system_command",
            "set_register", "set_register_verified", "state_get", "state_get_subtree",
            "state_subscribe", "events",
            "log_tail", "log_untail", "ui_tap", "ui_untap", "ui_tap_ping",
            "debug_session", "debug_stop",
            "config_reload", "logger_sink_enable", "logger_sink_disable",
        }
        assert names == expected


# ---------------------------------------------------------------------------
# Протокол: initialize / ping / tools/list
# ---------------------------------------------------------------------------


class TestProtocol:
    def test_initialize_echoes_supported_version(self) -> None:
        server, _ = make_server()
        res = call(server, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        result = res["result"]
        assert result["protocolVersion"] == "2025-06-18"
        assert "tools" in result["capabilities"]
        assert result["serverInfo"]["name"] == "backend-ctl"
        assert result["instructions"]

    def test_initialize_unknown_version_falls_back(self) -> None:
        server, _ = make_server()
        res = call(server, "initialize", {"protocolVersion": "1999-01-01"})
        assert res["result"]["protocolVersion"] == DEFAULT_PROTOCOL_VERSION

    def test_notification_has_no_response(self) -> None:
        server, _ = make_server()
        assert server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    def test_ping(self) -> None:
        server, _ = make_server()
        assert call(server, "ping")["result"] == {}

    def test_unknown_method_is_jsonrpc_error(self) -> None:
        server, _ = make_server()
        res = call(server, "resources/list")
        assert res["error"]["code"] == METHOD_NOT_FOUND

    def test_tools_list_matches_registry(self) -> None:
        server, _ = make_server()
        tools = call(server, "tools/list")["result"]["tools"]
        assert {t["name"] for t in tools} == {s.name for s in TOOLS}
        for t in tools:
            assert set(t) == {"name", "description", "inputSchema"}


# ---------------------------------------------------------------------------
# tools/call: диспетчеризация в driver, ошибки, reconnect-сброс
# ---------------------------------------------------------------------------


class TestToolsCall:
    def test_get_status_dispatches_to_driver(self) -> None:
        server, fake = make_server()
        res = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "preprocessor"}})
        assert res["result"]["isError"] is False
        assert tool_result(res) == {"success": True, "method": "get_status"}
        assert fake.calls == [("get_status", ("preprocessor",), {})]

    def test_send_command_passes_args_and_timeout(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {
            "name": "send_command",
            "arguments": {"target": "preprocessor", "command": "introspect.handlers",
                          "args": {"x": 1}, "timeout": 7},
        })
        assert fake.calls == [("send_command", ("preprocessor", "introspect.handlers", {"x": 1}), {"timeout": 7.0})]

    def test_state_get_maps_to_pm_command(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "state_get", "arguments": {"path": "processes.gui.status"}})
        assert fake.calls == [
            ("send_command", ("ProcessManager", "state.get", {"path": "processes.gui.status"}), {})
        ]

    def test_set_register_signature(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {
            "name": "set_register",
            "arguments": {"process": "preprocessor", "register": "resize", "field": "target_width", "value": 512},
        })
        assert fake.calls == [("set_register", ("preprocessor", "resize", "target_width", 512), {})]

    def test_set_register_verified_signature(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {
            "name": "set_register_verified",
            "arguments": {"process": "preprocessor", "register": "resize", "field": "target_width", "value": 512},
        })
        assert fake.calls == [("set_register_verified", ("preprocessor", "resize", "target_width", 512), {})]

    def test_capabilities_serializes_dataclass(self) -> None:
        server, _ = make_server()
        res = call(server, "tools/call", {"name": "capabilities", "arguments": {}})
        payload = tool_result(res)
        assert payload["ok"] is True
        assert payload["processes"]["ProcessManager"]["process"] == "ProcessManager"
        assert payload["topology"] == {"preprocessor": {"class": "x.Y"}}

    def test_events_timeout_capped(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "events", "arguments": {"timeout": 999, "max_items": 5}})
        name, _, kwargs = fake.calls[0]
        assert name == "events"
        assert kwargs["timeout"] <= MAX_EVENTS_TIMEOUT
        assert kwargs["max_items"] == 5

    def test_unknown_tool_is_invalid_params(self) -> None:
        server, _ = make_server()
        res = call(server, "tools/call", {"name": "no_such_tool", "arguments": {}})
        assert res["error"]["code"] == INVALID_PARAMS

    def test_handler_exception_is_tool_error_not_protocol_error(self) -> None:
        class BoomDriver(FakeDriver):
            def __getattr__(self, name):
                def _boom(*a, **k):
                    raise RuntimeError("boom")
                return _boom

        boom = BoomDriver()
        server = MCPServer(driver_factory=lambda: boom, log=lambda m: None)
        res = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        assert "error" not in res
        assert res["result"]["isError"] is True
        assert "boom" in res["result"]["content"][0]["text"]

    def test_backend_unavailable_resets_and_retries_next_call(self) -> None:
        attempts = {"n": 0}
        fake = FakeDriver()

        def factory():
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConnectionRefusedError(61, "Connection refused")
            return fake

        server = MCPServer(driver_factory=factory, log=lambda m: None)
        res1 = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        assert res1["result"]["isError"] is True
        assert "бэкенд недоступен" in res1["result"]["content"][0]["text"]
        res2 = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        assert res2["result"]["isError"] is False
        assert attempts["n"] == 2  # после отказа сервер не кэширует мёртвую фабрику


# ---------------------------------------------------------------------------
# stdio-цикл: сырые строки → ответы (без subprocess)
# ---------------------------------------------------------------------------


class TestServeLoop:
    def test_roundtrip_lines(self) -> None:
        server, _ = make_server()
        lines = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18"}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            "не-json-мусор",
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ]
        out = io.StringIO()
        server.serve(io.StringIO("\n".join(lines) + "\n"), out)
        responses = [json.loads(line) for line in out.getvalue().splitlines()]
        assert len(responses) == 3  # initialize + parse-error + tools/list (notification без ответа)
        assert responses[0]["id"] == 1 and "result" in responses[0]
        assert responses[1]["error"]["code"] == -32700
        assert responses[2]["id"] == 2 and "tools" in responses[2]["result"]


# ---------------------------------------------------------------------------
# Live: настоящий subprocess по stdio против живого бэкенда (harness_smoke)
# ---------------------------------------------------------------------------


class _StdioClient:
    """Мини-клиент MCP: пишет запросы в stdin subprocess'а, читает ответы построчно."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self._next_id = 0

    def request(self, method: str, params: Optional[dict] = None, timeout: float = 20.0) -> dict:
        self._next_id += 1
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            msg["params"] = params
        assert self._proc.stdin is not None and self._proc.stdout is not None
        self._proc.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

        holder: Dict[str, Any] = {}

        def _read() -> None:
            holder["line"] = self._proc.stdout.readline()

        t = threading.Thread(target=_read, daemon=True)
        t.start()
        t.join(timeout)
        line = holder.get("line")
        assert line, f"MCP-сервер не ответил на {method} за {timeout}s"
        res = json.loads(line)
        assert res.get("id") == self._next_id, f"ответ не на тот запрос: {res}"
        return res

    def notify(self, method: str) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self._proc.stdin.flush()


@pytest.mark.harness_smoke
def test_mcp_server_live_against_backend(headless_backend) -> None:
    """Acceptance 1.7: MCP-клиент по stdio вызывает инструменты против живого бэкенда.

    Тот же транспорт и формат, которым сервер зовёт Claude Code (.mcp.json →
    subprocess + newline-delimited JSON-RPC). Сценарий P3: initialize → tools/list →
    get_status(preprocessor) → introspect_handlers показывает register_update
    (диагноз «Этапа 2» — без GUI и без чтения исходников).
    """
    repo_root = Path(__file__).resolve().parents[2]
    env = dict(os.environ)
    # Порт — ЯВНО из driver'а session-фикстуры, не из env: соседние harness-тесты
    # (test_harness, порты 8766/8767) мутируют общий os.environ["BACKEND_CTL_PORT"],
    # и в полном прогоне env указывал бы на уже погашенный бэкенд (ловушка
    # «два бэкенда в одном прогоне», см. memory project_concurrent_backends_trap).
    env["BACKEND_CTL_PORT"] = str(headless_backend._port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "backend_ctl.mcp_server"],
        cwd=repo_root,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        client = _StdioClient(proc)

        init = client.request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        })
        assert init["result"]["serverInfo"]["name"] == "backend-ctl"
        client.notify("notifications/initialized")

        tools = client.request("tools/list")["result"]["tools"]
        assert {"capabilities", "get_status", "send_command"} <= {t["name"] for t in tools}

        status = client.request("tools/call", {
            "name": "get_status", "arguments": {"process": "preprocessor", "timeout": 8},
        })
        assert status["result"]["isError"] is False
        payload = json.loads(status["result"]["content"][0]["text"])
        assert payload.get("success") is True, payload

        handlers = client.request("tools/call", {
            "name": "introspect_handlers", "arguments": {"process": "preprocessor", "timeout": 8},
        })
        assert handlers["result"]["isError"] is False
        assert "register_update" in handlers["result"]["content"][0]["text"]
    finally:
        if proc.stdin is not None:
            proc.stdin.close()  # EOF → сервер штатно завершает serve()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
