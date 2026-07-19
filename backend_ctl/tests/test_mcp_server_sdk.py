# -*- coding: utf-8 -*-
"""Тесты MCP-сервера на официальном SDK (backend_ctl/mcp_server_sdk.py).

Юниты: адаптер реестра под SDK (list_tools с annotations, call_tool-диспатч,
safety-режимы, actionable-ошибки, resolve_mode) — на fake-driver, без реального
stdio/subprocess. Живой смоук (реальный `python -m backend_ctl.mcp_server_sdk`
из Claude Code против живого бэкенда) — отдельно, шаг владельца.
"""

from __future__ import annotations

import json
from typing import Any, List, Tuple

import pytest

from backend_ctl import mcp_errors
from backend_ctl.mcp_server_sdk import (
    MODE_ENV_VAR,
    SDKToolServer,
    resolve_mode,
)
from backend_ctl.mcp_tools import (
    MODE_FULL,
    MODE_NO_DESTRUCTIVE,
    MODE_READ_ONLY,
    build_registry,
)


class FakeDriver:
    """Запоминает вызовы, отвечает JSON-совместимой заглушкой (без транспорта)."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, tuple, dict]] = []

    def __getattr__(self, name: str):
        def _method(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args, kwargs))
            return {"success": True, "method": name}

        return _method

    def close(self) -> None:
        self.calls.append(("close", (), {}))


def make_server(mode: str = MODE_FULL) -> Tuple[SDKToolServer, FakeDriver]:
    fake = FakeDriver()
    return SDKToolServer(mode=mode, driver_factory=lambda: fake, log=lambda m: None), fake


def _text(result: Any) -> str:
    """Достать текст из успешного (list[TextContent]) ответа call_tool."""
    assert isinstance(result, list) and result, f"ожидался список контента, получено {result!r}"
    return result[0].text


def _error_text(result: Any) -> str:
    """Достать текст из ошибочного (CallToolResult isError) ответа call_tool."""
    assert getattr(result, "isError", False) is True, f"ожидался isError, получено {result!r}"
    return result.content[0].text


# --------------------------------------------------------------------------- #
#  Импорт без extra + resolve_mode                                            #
# --------------------------------------------------------------------------- #


def test_module_imports_without_calling_mcp() -> None:
    """Acceptance: модуль импортируется без установленного extra (ленивый импорт SDK)."""
    import backend_ctl.mcp_server_sdk as m  # noqa: PLC0415

    assert hasattr(m, "SDKToolServer") and hasattr(m, "main")


class TestResolveMode:
    def test_default_full(self) -> None:
        assert resolve_mode(env={}) == MODE_FULL

    def test_read_only_flag_wins(self) -> None:
        assert resolve_mode(read_only=True, env={MODE_ENV_VAR: MODE_FULL}) == MODE_READ_ONLY

    def test_disable_destructive_flag(self) -> None:
        assert resolve_mode(disable_destructive=True, env={}) == MODE_NO_DESTRUCTIVE

    def test_env_used_when_no_flags(self) -> None:
        assert resolve_mode(env={MODE_ENV_VAR: MODE_READ_ONLY}) == MODE_READ_ONLY

    def test_unknown_env_falls_back_to_full(self) -> None:
        assert resolve_mode(env={MODE_ENV_VAR: "garbage"}) == MODE_FULL


# --------------------------------------------------------------------------- #
#  list_tools: annotations + скрытие по режиму                                #
# --------------------------------------------------------------------------- #


class TestListTools:
    def test_full_lists_all_tools_with_annotations(self) -> None:
        server, _ = make_server(MODE_FULL)
        tools = server.list_tools()
        assert {t.name for t in tools} == set(build_registry())
        # capabilities — read-only hint; set_register — destructive
        by_name = {t.name: t for t in tools}
        assert by_name["capabilities"].annotations.readOnlyHint is True
        assert by_name["set_register"].annotations.destructiveHint is True
        assert by_name["send_command"].annotations.openWorldHint is True

    def test_read_only_hides_write_and_escalated(self) -> None:
        server, _ = make_server(MODE_READ_ONLY)
        names = {t.name for t in server.list_tools()}
        assert "set_register" not in names  # write скрыт
        assert "system_command" not in names  # escalated скрыт
        assert "get_status" in names and "state_subscribe" in names  # read/subscribe видны
        assert "send_command" in names  # escalated, но в read-only условно доступен (whitelist) → виден

    def test_no_destructive_hides_write(self) -> None:
        server, _ = make_server(MODE_NO_DESTRUCTIVE)
        names = {t.name for t in server.list_tools()}
        assert "telemetry_set" not in names  # write скрыт
        assert "system_command" not in names  # чистый escalated скрыт
        # send_command условно доступен (read-safe) → виден в обоих ограниченных режимах
        assert "send_command" in names
        assert "telemetry_snapshot" in names and "watch_like_gui" in names


# --------------------------------------------------------------------------- #
#  call_tool: диспатч + safety-гейт + actionable-ошибки                       #
# --------------------------------------------------------------------------- #


class TestCallToolDispatch:
    def test_known_tool_dispatches_to_driver(self) -> None:
        server, fake = make_server()
        res = server.call_tool("get_status", {"process": "preprocessor"})
        assert json.loads(_text(res)) == {"success": True, "method": "get_status"}
        assert fake.calls[-1] == ("get_status", ("preprocessor",), {})

    def test_unknown_tool_actionable_error(self) -> None:
        server, _ = make_server()
        res = server.call_tool("get_statuz", {})  # опечатка
        msg = _error_text(res)
        assert "неизвестный инструмент" in msg
        assert "get_status" in msg  # ближайшее имя подсказано

    def test_telemetry_snapshot_local_read(self) -> None:
        server, fake = make_server()
        res = server.call_tool("telemetry_snapshot", {"process": "cam", "metric": "fps"})
        assert json.loads(_text(res))["success"] is True
        assert fake.calls[-1] == ("telemetry_snapshot", ("cam", "fps"), {})


class TestSafetyModes:
    def test_read_only_blocks_write_before_driver(self) -> None:
        server, fake = make_server(MODE_READ_ONLY)
        res = server.call_tool("set_register", {"process": "p", "register": "r", "field": "f", "value": 1})
        msg = _error_text(res)
        assert "заблокирован" in msg and "read-only" in msg
        # driver НЕ вызван (гейт до подключения) — fake без вызовов инструмента
        assert not any(c[0] == "set_register" for c in fake.calls)

    def test_read_only_allows_read(self) -> None:
        server, _ = make_server(MODE_READ_ONLY)
        res = server.call_tool("get_status", {"process": "p"})
        assert json.loads(_text(res))["success"] is True

    def test_read_only_send_command_readsafe_allowed(self) -> None:
        server, fake = make_server(MODE_READ_ONLY)
        res = server.call_tool("send_command", {"target": "cam", "command": "introspect.handlers"})
        assert json.loads(_text(res))["success"] is True
        assert any(c[0] == "send_command" for c in fake.calls)

    def test_read_only_send_command_write_blocked(self) -> None:
        server, fake = make_server(MODE_READ_ONLY)
        res = server.call_tool("send_command", {"target": "cam", "command": "recipe.activate"})
        msg = _error_text(res)
        assert "introspect." in msg  # назвал разрешённые read-префиксы
        assert not any(c[0] == "send_command" for c in fake.calls)

    def test_no_destructive_blocks_telemetry_set(self) -> None:
        server, _ = make_server(MODE_NO_DESTRUCTIVE)
        res = server.call_tool("telemetry_set", {"process": "p", "metric": "fps", "enabled": False})
        assert "заблокирован" in _error_text(res)

    def test_no_destructive_allows_subscribe(self) -> None:
        server, _ = make_server(MODE_NO_DESTRUCTIVE)
        res = server.call_tool("watch_like_gui", {})
        assert json.loads(_text(res))["success"] is True

    def test_no_destructive_send_command_readsafe_allowed(self) -> None:
        # Согласованность режимов: no-destructive, как и read-only, пропускает read-safe send_command.
        server, fake = make_server(MODE_NO_DESTRUCTIVE)
        res = server.call_tool("send_command", {"target": "cam", "command": "introspect.handlers"})
        assert json.loads(_text(res))["success"] is True
        assert any(c[0] == "send_command" for c in fake.calls)

    def test_no_destructive_send_command_write_blocked(self) -> None:
        server, fake = make_server(MODE_NO_DESTRUCTIVE)
        res = server.call_tool("send_command", {"target": "cam", "command": "recipe.activate"})
        assert "introspect." in _error_text(res)
        assert not any(c[0] == "send_command" for c in fake.calls)


# --------------------------------------------------------------------------- #
#  mcp_errors — чистые построители                                            #
# --------------------------------------------------------------------------- #


class TestEndToEndOverSdk:
    """Интеграция через РЕАЛЬНЫЙ протокол SDK (in-memory client↔server): проверяет
    обвязку build_server (list_tools/call_tool идут через настоящую сессию)."""

    @pytest.mark.asyncio
    async def test_initialize_list_and_call(self) -> None:
        from mcp.shared.memory import create_connected_server_and_client_session

        from backend_ctl.mcp_server_sdk import build_server

        fake = FakeDriver()
        ts = SDKToolServer(driver_factory=lambda: fake, log=lambda m: None)
        server = build_server(ts)
        async with create_connected_server_and_client_session(server) as client:
            listed = await client.list_tools()
            names = {t.name for t in listed.tools}
            assert names == set(build_registry())
            # annotations доехали через протокол
            caps = next(t for t in listed.tools if t.name == "capabilities")
            assert caps.annotations.readOnlyHint is True

            result = await client.call_tool("get_status", {"process": "preprocessor"})
            assert result.isError is False
            assert json.loads(result.content[0].text) == {"success": True, "method": "get_status"}

    @pytest.mark.asyncio
    async def test_read_only_hides_and_blocks_over_sdk(self) -> None:
        from mcp.shared.memory import create_connected_server_and_client_session

        from backend_ctl.mcp_server_sdk import build_server

        fake = FakeDriver()
        ts = SDKToolServer(mode=MODE_READ_ONLY, driver_factory=lambda: fake, log=lambda m: None)
        async with create_connected_server_and_client_session(build_server(ts)) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert "set_register" not in names  # скрыт из каталога
            # и заблокирован при прямом вызове (isError с actionable-текстом)
            res = await client.call_tool("set_register", {"process": "p", "register": "r", "field": "f", "value": 1})
            assert res.isError is True
            assert "read-only" in res.content[0].text


class TestPerSessionLifespan:
    """D.2 Step 2: build_server принимает фабрику → свежий SDKToolServer на КАЖДУЮ
    MCP-сессию (мультиплекс поверх изоляции D.1a). Инстанс — back-compat (одна на процесс)."""

    def test_factory_normalization_instance_and_callable(self) -> None:
        from backend_ctl.mcp_server_sdk import _as_tool_server_factory

        inst, _ = make_server()
        assert _as_tool_server_factory(inst)() is inst  # инстанс → тот же
        fresh = _as_tool_server_factory(lambda: inst)  # callable → сама фабрика
        assert fresh() is inst

    def test_factory_rejects_garbage(self) -> None:
        from backend_ctl.mcp_server_sdk import _as_tool_server_factory

        with pytest.raises(TypeError):
            _as_tool_server_factory(object())

    @pytest.mark.asyncio
    async def test_lifespan_creates_tool_server_per_session(self) -> None:
        from mcp.shared.memory import create_connected_server_and_client_session

        from backend_ctl.mcp_server_sdk import build_server

        created: List[SDKToolServer] = []

        def factory() -> SDKToolServer:
            ts = SDKToolServer(driver_factory=lambda: FakeDriver(), log=lambda m: None)
            created.append(ts)
            return ts

        server = build_server(factory)
        async with create_connected_server_and_client_session(server) as client:
            assert {t.name for t in (await client.list_tools()).tools} == set(build_registry())
        async with create_connected_server_and_client_session(server) as client:
            res = await client.call_tool("get_status", {"process": "p"})
            assert res.isError is False
        # свежий tool_server на каждую MCP-сессию (не разделяется между сессиями)
        assert len(created) == 2
        assert created[0] is not created[1]


class TestMcpErrors:
    def test_suggest_tools_finds_near(self) -> None:
        assert "get_status" in mcp_errors.suggest_tools("get_statuz", build_registry().keys())

    def test_unknown_tool_names_alternatives(self) -> None:
        msg = mcp_errors.unknown_tool_error("capabilitiez", build_registry().keys())
        assert "capabilities" in msg and "tools/list" in msg

    def test_blocked_tool_lists_allowed(self) -> None:
        msg = mcp_errors.blocked_tool_error("set_register", MODE_READ_ONLY, ["get_status", "events"])
        assert "set_register" in msg and "get_status" in msg

    def test_restricted_command_blocked_names_prefixes(self) -> None:
        msg = mcp_errors.restricted_command_blocked_error("recipe.activate")
        assert "introspect." in msg and "state.get" in msg


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
