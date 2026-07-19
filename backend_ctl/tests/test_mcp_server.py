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

from backend_ctl.driver import BackendDriver, Capabilities, ProcessCapabilities
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
                    processes={
                        "ProcessManager": ProcessCapabilities(True, "ProcessManager", [], [], {}),
                        # preprocessor присутствует как реальный адресат (в проде свод несёт
                        # карточки ВСЕХ процессов) — иначе E.2-валидация ложно заблокирует send_command.
                        "preprocessor": ProcessCapabilities(True, "preprocessor", [], [], {}),
                    },
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
            "capabilities",
            "system_overview",
            "get_status",
            "introspect_handlers",
            "introspect_registers",
            "introspect_router_stats",
            "introspect_queues",
            "introspect_plugins",
            "introspect_memory",
            "supervision_status",
            "send_command",
            "system_command",
            "set_register",
            "set_register_verified",
            "register_snapshot",
            "register_restore",
            "register_confirm",
            "register_rollback_log",
            "state_get",
            "state_get_subtree",
            "state_subscribe",
            "events",
            "events_page",
            "await_condition",
            "log_tail",
            "log_untail",
            "observability_tail",
            "observability_untail",
            "watch_like_gui",
            "unwatch",
            "ui_tap",
            "ui_untap",
            "ui_tap_ping",
            "debug_session",
            "debug_stop",
            "config_reload",
            "logger_sink_enable",
            "logger_sink_disable",
            "telemetry_reconfigure",
            "telemetry_set",
            "telemetry_snapshot",
            "telemetry_history",
            # flight recorder (D.4)
            "record_start",
            "record_stop",
            "record_status",
            "record_load",
            "record_unload",
            "record_dump",
            # audit (E.1)
            "session_log",
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

    def test_introspect_memory_dispatches_to_driver(self) -> None:
        # Ф2 Task 2.4: introspect_memory доходит до driver (read-only инвентарь памяти).
        server, fake = make_server()
        res = call(server, "tools/call", {"name": "introspect_memory", "arguments": {"process": "preprocessor"}})
        assert res["result"]["isError"] is False
        assert tool_result(res) == {"success": True, "method": "introspect_memory"}
        assert fake.calls == [("introspect_memory", ("preprocessor",), {})]

    def test_telemetry_snapshot_dispatches_to_driver(self) -> None:
        # Task 2.3: telemetry_snapshot — локальное чтение read-model (0 IPC), фильтры process/metric.
        server, fake = make_server()
        res = call(
            server,
            "tools/call",
            {"name": "telemetry_snapshot", "arguments": {"process": "cam", "metric": "fps"}},
        )
        assert res["result"]["isError"] is False
        assert tool_result(res) == {"success": True, "method": "telemetry_snapshot"}
        assert fake.calls == [("telemetry_snapshot", ("cam", "fps"), {})]

    def test_telemetry_snapshot_no_args_passes_none(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "telemetry_snapshot", "arguments": {}})
        assert fake.calls == [("telemetry_snapshot", (None, None), {})]

    def test_telemetry_history_dispatches_to_driver(self) -> None:
        server, fake = make_server()
        res = call(
            server,
            "tools/call",
            {"name": "telemetry_history", "arguments": {"path": "processes.cam.state.fps", "limit": 50}},
        )
        assert res["result"]["isError"] is False
        assert tool_result(res) == {"success": True, "method": "telemetry_history"}
        assert fake.calls == [("telemetry_history", ("processes.cam.state.fps",), {"limit": 50})]

    def test_send_command_passes_args_and_timeout(self) -> None:
        server, fake = make_server()
        call(
            server,
            "tools/call",
            {
                "name": "send_command",
                "arguments": {
                    "target": "preprocessor",
                    "command": "introspect.handlers",
                    "args": {"x": 1},
                    "timeout": 7,
                },
            },
        )
        # E.2: send_command предваряется одним capabilities()-fan-out (кэш сессии) для
        # валидации args по схеме; затем сам вызов с аргументами/таймаутом.
        assert fake.calls == [
            ("capabilities", (), {}),
            ("send_command", ("preprocessor", "introspect.handlers", {"x": 1}), {"timeout": 7.0}),
        ]

    def test_state_get_maps_to_pm_command(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "state_get", "arguments": {"path": "processes.gui.status"}})
        assert fake.calls == [("send_command", ("ProcessManager", "state.get", {"path": "processes.gui.status"}), {})]

    def test_set_register_signature(self) -> None:
        server, fake = make_server()
        call(
            server,
            "tools/call",
            {
                "name": "set_register",
                "arguments": {"process": "preprocessor", "register": "resize", "field": "target_width", "value": 512},
            },
        )
        assert fake.calls == [("set_register", ("preprocessor", "resize", "target_width", 512), {})]

    def test_set_register_verified_signature(self) -> None:
        server, fake = make_server()
        call(
            server,
            "tools/call",
            {
                "name": "set_register_verified",
                "arguments": {"process": "preprocessor", "register": "resize", "field": "target_width", "value": 512},
            },
        )
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
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}
            ),
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
    env["BACKEND_CTL_PORT"] = str(headless_backend.port)
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

        init = client.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        )
        assert init["result"]["serverInfo"]["name"] == "backend-ctl"
        client.notify("notifications/initialized")

        tools = client.request("tools/list")["result"]["tools"]
        assert {"capabilities", "get_status", "send_command"} <= {t["name"] for t in tools}

        status = client.request(
            "tools/call",
            {
                "name": "get_status",
                "arguments": {"process": "preprocessor", "timeout": 8},
            },
        )
        assert status["result"]["isError"] is False
        payload = json.loads(status["result"]["content"][0]["text"])
        assert payload.get("success") is True, payload

        handlers = client.request(
            "tools/call",
            {
                "name": "introspect_handlers",
                "arguments": {"process": "preprocessor", "timeout": 8},
            },
        )
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


# ---------------------------------------------------------------------------
# Task 0.3: durable-подписки переживают реконнект + контракт ошибок
# ---------------------------------------------------------------------------


class _SubFakeDriver:
    """Fake-driver с реальной семантикой подписок для проверки reconnect-replay."""

    def __init__(self) -> None:
        self._intents: List[Dict[str, Any]] = []
        self.replayed: List[Dict[str, Any]] = []
        self.closed = False
        self.fail = False

    def state_subscribe(self, pattern, *, timeout=None):
        self._intents.append({"command": "state.subscribe", "target": "ProcessManager", "args": {"pattern": pattern}})
        return {"success": True}

    def log_tail(self, process, *, level="ERROR", timeout=None):
        self._intents.append(
            {"command": "log.tail.subscribe", "target": process, "args": {"subscriber": "backend_ctl", "level": level}}
        )
        return {"success": True}

    def log_untail(self, process, *, timeout=None):
        self._intents = [
            i for i in self._intents if not (i["command"] == "log.tail.subscribe" and i["target"] == process)
        ]
        return {"success": True}

    def get_status(self, process, *, timeout=None):
        if self.fail:
            raise OSError("connection lost")
        return {"success": True, "method": "get_status"}

    def export_subscriptions(self):
        return list(self._intents)

    def import_subscriptions(self, intents):
        self._intents = list(intents)

    def replay_subscriptions(self):
        self.replayed = list(self._intents)
        return [{"command": i["command"], "target": i["target"], "success": True} for i in self._intents]

    def close(self):
        self.closed = True


class TestReconnectReplay:
    def test_reconnect_replays_subscriptions_and_reports(self) -> None:
        d1 = _SubFakeDriver()
        d2 = _SubFakeDriver()
        seq = iter([d1, d2])
        server = MCPServer(driver_factory=lambda: next(seq), log=lambda m: None)

        # Агент подписался — намерение записано на d1.
        call(server, "tools/call", {"name": "state_subscribe", "arguments": {"pattern": "processes.**"}})
        assert d1.export_subscriptions(), "подписка должна осесть в реестре driver'а"

        # Соединение оборвалось на следующем вызове → сброс driver'а.
        d1.fail = True
        r1 = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        assert r1["result"]["isError"] is True
        assert d1.closed is True

        # Следующий вызов — новый driver d2 получает намерения и replay'ит их.
        r2 = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        payload = tool_result(r2)
        assert payload.get("reconnected") is True
        assert any(x["command"] == "state.subscribe" for x in payload["resubscribed"])
        assert d2.replayed, "replay должен реально выполниться на новом driver'е"

    def test_no_reconnect_report_without_prior_subscriptions(self) -> None:
        # Без подписок реконнект не докладывается (нечего восстанавливать).
        d1 = _SubFakeDriver()
        d2 = _SubFakeDriver()
        seq = iter([d1, d2])
        server = MCPServer(driver_factory=lambda: next(seq), log=lambda m: None)
        d1.fail = True
        call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        r2 = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        payload = tool_result(r2)
        assert "reconnected" not in payload
        assert d2.replayed == []

    def test_unsubscribed_not_resurrected_after_second_reconnect(self) -> None:
        # Регресс на MAJOR #1 ревью: агент отписался → второй реконнект НЕ воскрешает
        # снятую подписку (раньше guard `if intents:` держал стухший _sub_intents).
        d1, d2, d3 = _SubFakeDriver(), _SubFakeDriver(), _SubFakeDriver()
        seq = iter([d1, d2, d3])
        server = MCPServer(driver_factory=lambda: next(seq), log=lambda m: None)

        # (1) подписка на d1
        call(server, "tools/call", {"name": "log_tail", "arguments": {"process": "cam"}})
        assert d1.export_subscriptions()

        # (2) обрыв → (3) реконнект d2 replay'ит подписку
        d1.fail = True
        call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        r = tool_result(call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}}))
        assert r.get("reconnected") is True
        assert d2.replayed and d2.export_subscriptions()

        # (4) агент отписался на d2 → реестр пуст
        call(server, "tools/call", {"name": "log_untail", "arguments": {"process": "cam"}})
        assert d2.export_subscriptions() == []

        # (5) второй обрыв → (6) реконнект d3 НЕ должен воскрешать снятую подписку
        d2.fail = True
        call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        r3 = tool_result(call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}}))
        assert d3.replayed == [], "снятая подписка не должна воскресать после реконнекта"
        assert "reconnected" not in r3


class _WatchFakeDriver(_SubFakeDriver):
    """Fake-driver с watch-манифестом/resume для проверки восстановления контура (F2)."""

    def __init__(self) -> None:
        super().__init__()
        self.resumed_with: Any = None
        self._active_watch = False

    def watch_like_gui(self, **kwargs):
        self._active_watch = True
        return {"success": True, "processes": ["gui"], "tail_level": "WARNING"}

    def watch_manifest(self):
        if not self._active_watch:
            return {"active": False}
        return {"active": True, "patterns": ["processes.**"], "tail_level": "WARNING", "processes": ["gui"]}

    def resume_watch(self, manifest):
        self.resumed_with = manifest
        self._active_watch = True
        return {"resumed": True, "processes": ["gui"], "patterns": ["processes.**"]}


class TestReconnectResumesWatch:
    """F2: реконнект восстанавливает watch-КОНТУР на новом driver'е, не только подписки."""

    def test_reconnect_resumes_watch_loop(self) -> None:
        d1, d2 = _WatchFakeDriver(), _WatchFakeDriver()
        seq = iter([d1, d2])
        server = MCPServer(driver_factory=lambda: next(seq), log=lambda m: None)

        # Агент включил watch → манифест активен на d1.
        call(server, "tools/call", {"name": "watch_like_gui", "arguments": {}})
        assert d1._active_watch is True

        # Обрыв → сброс d1 (манифест снят ДО закрытия).
        d1.fail = True
        call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        assert d1.closed is True

        # Реконнект → d2 поднимает watch-контур из манифеста и докладывает.
        r2 = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        payload = tool_result(r2)
        assert payload.get("watch_resumed") is True
        assert d2.resumed_with is not None and d2.resumed_with.get("active") is True

    def test_inactive_watch_not_resumed(self) -> None:
        # Watch не включали → манифест неактивен → resume не зовётся (нет ложного контура).
        d1, d2 = _WatchFakeDriver(), _WatchFakeDriver()
        seq = iter([d1, d2])
        server = MCPServer(driver_factory=lambda: next(seq), log=lambda m: None)
        call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        d1.fail = True
        call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        r2 = call(server, "tools/call", {"name": "get_status", "arguments": {"process": "p"}})
        payload = tool_result(r2)
        assert "watch_resumed" not in payload
        assert d2.resumed_with is None


class TestReadinessProbe:
    def test_await_ready_polls_until_success(self) -> None:
        from backend_ctl.mcp_driver_session import DriverSession

        class _Drv:
            def __init__(self):
                self.n = 0

            def introspect_status(self, process, *, timeout=None):
                self.n += 1
                return {"success": self.n >= 2}  # готов со второй пробы

        drv = _Drv()
        session = DriverSession(driver_factory=lambda: None, log=lambda m: None)
        assert session._await_ready(drv, attempts=3, probe_timeout=0.01) is True
        assert drv.n == 2

    def test_await_ready_gives_up_after_attempts(self) -> None:
        from backend_ctl.mcp_driver_session import DriverSession

        class _Drv:
            def introspect_status(self, process, *, timeout=None):
                return {"success": False, "error": "timeout"}

        session = DriverSession(driver_factory=lambda: None, log=lambda m: None)
        assert session._await_ready(_Drv(), attempts=3, probe_timeout=0.01) is False


class TestErrorContract:
    """Все dict-обёртки на неподключённом транспорте → success=False + error."""

    def test_dict_wrappers_uniform_error_on_disconnected_transport(self) -> None:
        d = BackendDriver()  # _sock is None → транспорт не подключён
        checks = [
            lambda: d.send_command("p", "introspect.handlers"),
            lambda: d.system_command({"action": "noop"}),
            lambda: d.introspect_handlers("p"),
            lambda: d.introspect_registers("p"),
            lambda: d.introspect_status("p"),
            lambda: d.get_status("p"),
            lambda: d.introspect_router_stats("p"),
            lambda: d.introspect_queues("p"),
            lambda: d.introspect_plugins("p"),
            lambda: d.introspect_capabilities("p"),
            lambda: d.set_register("p", "resize", "w", 1),
            lambda: d.config_reload("p"),
            lambda: d.logger_sink_enable("p", "console"),
            lambda: d.logger_sink_disable("p", "console"),
            lambda: d.state_subscribe("processes.**"),
            lambda: d.log_tail("p"),
            lambda: d.log_untail("p"),
            lambda: d.observability_tail("p"),
            lambda: d.observability_untail("p"),
            lambda: d.ui_tap("gui"),
            lambda: d.ui_untap("gui"),
        ]
        for fn in checks:
            res = fn()
            assert isinstance(res, dict), fn
            assert res.get("success") is False, (fn, res)
            assert "error" in res, (fn, res)


class TestTelemetryTools:
    """Task 0.5: telemetry_* зарегистрированы в MCP и диспетчатся на driver 1:1."""

    def test_reconfigure_passes_only_present_keys(self) -> None:
        server, fake = make_server()
        call(
            server,
            "tools/call",
            {
                "name": "telemetry_reconfigure",
                "arguments": {
                    "process": "preprocessor",
                    "publish": {"metrics": {"fps": {"enabled": True}}},
                    "mode": "merge",
                },
            },
        )
        name, args, kwargs = fake.calls[0]
        assert name == "telemetry_reconfigure"
        assert args == ("preprocessor",)
        assert kwargs == {"publish": {"metrics": {"fps": {"enabled": True}}}, "mode": "merge"}
        assert "throttle" not in kwargs  # не передан → _UNSET-семантика сохранена

    def test_reconfigure_defaults_process_to_all(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "telemetry_reconfigure", "arguments": {"throttle": {"fps": 0.1}}})
        _, args, kwargs = fake.calls[0]
        assert args == ("all",)
        assert kwargs == {"throttle": {"fps": 0.1}}

    def test_reconfigure_explicit_null_publish_preserved(self) -> None:
        # Явный null у publish = «выключить gate» — должен дойти до driver (не потеряться).
        server, fake = make_server()
        call(server, "tools/call", {"name": "telemetry_reconfigure", "arguments": {"process": "p", "publish": None}})
        _, args, kwargs = fake.calls[0]
        assert kwargs == {"publish": None}

    def test_set_dispatches_1to1(self) -> None:
        server, fake = make_server()
        call(
            server,
            "tools/call",
            {
                "name": "telemetry_set",
                "arguments": {"process": "p", "metric": "fps", "enabled": False, "plane": "publisher"},
            },
        )
        name, args, kwargs = fake.calls[0]
        assert name == "telemetry_set"
        assert args == ("p", "fps")
        assert kwargs == {"enabled": False, "plane": "publisher"}

    def test_tools_present_in_list(self) -> None:
        server, _ = make_server()
        tools = {t["name"] for t in call(server, "tools/list")["result"]["tools"]}
        assert {"telemetry_reconfigure", "telemetry_set"} <= tools


class TestObservabilityAndWatchTools:
    """Task 2.1/2.2: observability_tail/untail + watch_like_gui/unwatch диспетчатся на driver."""

    def test_observability_tail_dispatches(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "observability_tail", "arguments": {"process": "preprocessor"}})
        name, args, kwargs = fake.calls[0]
        assert name == "observability_tail"
        assert args == ("preprocessor",)

    def test_observability_untail_dispatches(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "observability_untail", "arguments": {"process": "preprocessor"}})
        name, args, _ = fake.calls[0]
        assert name == "observability_untail" and args == ("preprocessor",)

    def test_watch_like_gui_passes_patterns_and_level(self) -> None:
        server, fake = make_server()
        call(
            server,
            "tools/call",
            {"name": "watch_like_gui", "arguments": {"patterns": ["system.**"], "tail_level": "INFO"}},
        )
        name, _, kwargs = fake.calls[0]
        assert name == "watch_like_gui"
        assert kwargs["patterns"] == ("system.**",)
        assert kwargs["tail_level"] == "INFO"

    def test_watch_like_gui_defaults_when_no_args(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "watch_like_gui", "arguments": {}})
        name, _, kwargs = fake.calls[0]
        assert name == "watch_like_gui"
        # Без явных аргументов driver берёт свои дефолты (patterns не передан).
        assert "patterns" not in kwargs

    def test_unwatch_dispatches(self) -> None:
        server, fake = make_server()
        call(server, "tools/call", {"name": "unwatch", "arguments": {}})
        assert fake.calls[0][0] == "unwatch"

    def test_new_tools_present_in_list(self) -> None:
        server, _ = make_server()
        tools = {t["name"] for t in call(server, "tools/list")["result"]["tools"]}
        assert {"observability_tail", "observability_untail", "watch_like_gui", "unwatch"} <= tools
