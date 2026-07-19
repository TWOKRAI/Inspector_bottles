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

    @pytest.mark.asyncio
    async def test_call_tool_runs_in_worker_thread(self) -> None:
        """D.2 Step 3: диспатч call_tool оффлоудится в worker-thread (не в event loop) —
        одна блокирующая сессия (await_condition/долгий introspect) не морозит остальные."""
        import threading

        from mcp.shared.memory import create_connected_server_and_client_session

        from backend_ctl.mcp_server_sdk import build_server

        loop_thread = threading.get_ident()
        seen: dict = {}

        class RecordingDriver(FakeDriver):
            def get_status(self, *a: Any, **k: Any) -> Any:
                seen["thread"] = threading.get_ident()
                return {"success": True, "method": "get_status"}

        server = build_server(lambda: SDKToolServer(driver_factory=lambda: RecordingDriver(), log=lambda m: None))
        async with create_connected_server_and_client_session(server) as client:
            res = await client.call_tool("get_status", {"process": "p"})
            assert res.isError is False
        # driver-вызов исполнился в ДРУГОМ потоке, чем event loop → оффлоуд состоялся
        assert seen.get("thread") is not None
        assert seen["thread"] != loop_thread

    @pytest.mark.asyncio
    async def test_two_sessions_have_isolated_drivers(self) -> None:
        """D.2 Step 7: две MCP-сессии → разные driver-объекты с изолированными реестрами
        подписок (мультиплекс поверх D.1a: каждая сессия = свой driver → свой сокет/session).
        Заодно end-to-end проверяет cleanup Step 5 через реальный lifespan-выход."""
        from mcp.shared.memory import create_connected_server_and_client_session

        from backend_ctl.driver import BackendDriver
        from backend_ctl.mcp_server_sdk import build_server

        drivers: List[BackendDriver] = []

        def factory() -> SDKToolServer:
            drv = BackendDriver("127.0.0.1", 59999)  # не подключаем — стабим send_command
            drv.send_command = lambda *a, **k: {"success": True}  # type: ignore[method-assign]
            drivers.append(drv)
            return SDKToolServer(driver_factory=lambda: drv, log=lambda m: None)

        server = build_server(factory)
        # сессия A: подписка регистрирует durable-намерение в СВОЁМ driver'е
        async with create_connected_server_and_client_session(server) as client:
            assert (await client.call_tool("log_tail", {"process": "cam"})).isError is False
            assert len(drivers[0]._subscriptions.export()) >= 1  # намерение в driver'е сессии A
        # выход сессии A → close_graceful → unsubscribe_all снял намерение (долг D.1 §12)
        assert drivers[0]._subscriptions.export() == []

        # сессия B: свежий driver — его реестр пуст, подписка сессии A не протекла
        async with create_connected_server_and_client_session(server) as client:
            assert (await client.call_tool("get_status", {"process": "cam"})).isError is False

        assert len(drivers) == 2 and drivers[0] is not drivers[1]
        assert drivers[1]._subscriptions.export() == []


class TestHttpRunner:
    """D.2 Step 4: HTTP-раннер. Полный сетевой прогон — live-смоук (Step 8, маркер live);
    здесь — чистые пины парсинга bind и совместимости wiring со StreamableHTTPSessionManager."""

    def test_parse_http_bind(self) -> None:
        from backend_ctl.mcp_server_sdk import _parse_http_bind

        assert _parse_http_bind("127.0.0.1:8901") == ("127.0.0.1", 8901)
        assert _parse_http_bind("localhost:9000") == ("localhost", 9000)

    def test_parse_http_bind_rejects_portless(self) -> None:
        from backend_ctl.mcp_server_sdk import _parse_http_bind

        with pytest.raises(ValueError):
            _parse_http_bind("8901")

    def test_main_http_bad_bind_returns_clean_error(self) -> None:
        # ревью #1: кривой --http-bind → код 2 (понятное сообщение), не трейсбек и не serve
        from backend_ctl import mcp_server_sdk as m

        assert m.main(["--http", "--http-bind", "garbage"]) == 2

    def test_build_server_compatible_with_streamable_manager(self) -> None:
        """build_server(factory) конструируется в StreamableHTTPSessionManager (stateful,
        idle-TTL, security) без ошибок типов/валидаций — wiring HTTP-раннера корректен."""
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.server.transport_security import TransportSecuritySettings

        from backend_ctl.mcp_server_sdk import build_server

        server = build_server(lambda: SDKToolServer(driver_factory=lambda: FakeDriver(), log=lambda m: None))
        mgr = StreamableHTTPSessionManager(
            app=server,
            stateless=False,
            session_idle_timeout=1800.0,
            security_settings=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=["127.0.0.1:8901"],
                allowed_origins=["http://127.0.0.1:8901"],
            ),
        )
        assert mgr is not None


class TestGracefulCleanup:
    """D.2 Step 5: завершение MCP-сессии снимает durable-подписки на бэкенде (долг D.1 §12)."""

    def test_unsubscribe_all_sends_untail_per_intent(self) -> None:
        from backend_ctl.driver import BackendDriver

        drv = BackendDriver("127.0.0.1", 59999)  # не подключаем — стабим send_command
        sent: List[tuple] = []

        def rec(target: str, command: str, args: Any = None, *, timeout: Any = None) -> dict:
            sent.append((target, command, dict(args or {})))
            return {"success": True}

        drv.send_command = rec  # type: ignore[method-assign]
        drv._subscriptions.add("log.tail.subscribe", "cam", {"subscriber": "backend_ctl.abc", "level": "INFO"})
        drv._subscriptions.add("observability.tail.subscribe", "cam", {"subscriber": "backend_ctl.abc"})
        drv._subscriptions.add("ui.tap.subscribe", "gui", {"subscriber": "backend_ctl.abc"})
        drv._subscriptions.add(
            "state.subscribe", "ProcessManager", {"pattern": "processes.**", "subscriber": "backend_ctl.abc"}
        )

        report = drv.unsubscribe_all(timeout=0.5)
        cmds = {c for _, c, _ in sent}
        assert {"log.tail.unsubscribe", "observability.tail.unsubscribe", "ui.tap.unsubscribe"} <= cmds
        # state.subscribe освобождается закрытием сокета — серверная команда снятия НЕ шлётся
        assert not any(c.startswith("state.") for _, c, _ in sent)
        assert all(r["success"] for r in report)
        assert drv._subscriptions.export() == []  # реестр опустошён

    def test_close_graceful_unsubscribes_then_closes(self) -> None:
        calls: List[str] = []

        class RecordingDriver(FakeDriver):
            def unwatch(self, *a: Any, **k: Any) -> Any:
                calls.append("unwatch")
                return {"success": True}

            def unsubscribe_all(self, *a: Any, **k: Any) -> Any:
                calls.append("unsubscribe_all")
                return []

            def export_subscriptions(self, *a: Any, **k: Any) -> Any:
                return []

            def watch_manifest(self, *a: Any, **k: Any) -> Any:
                return None

            def close(self) -> None:
                calls.append("close")

        from backend_ctl.mcp_driver_session import DriverSession

        ds = DriverSession(driver_factory=lambda: RecordingDriver(), log=lambda m: None)
        ds.ensure()
        ds.close_graceful()
        # unwatch и unsubscribe_all — пока сокет жив; close — последним (порядок §5.2)
        assert calls == ["unwatch", "unsubscribe_all", "close"]


class TestIsolationProbe:
    """D.2 Step 6: HTTP-режим fail-fast при backend session_isolation=OFF (§5.4)."""

    def test_extract_isolation_various_shapes(self) -> None:
        from backend_ctl.mcp_driver_session import _extract_backend_ctl_isolation

        # dict-по-имени
        on = {"channels": {"backend_ctl": {"name": "backend_ctl", "session_isolation": True}}}
        assert _extract_backend_ctl_isolation(on) is True
        # вложенный список каналов
        off = {"router_stats": {"channels": [{"name": "other"}, {"name": "backend_ctl", "session_isolation": False}]}}
        assert _extract_backend_ctl_isolation(off) is False
        # нет канала backend_ctl → None
        assert _extract_backend_ctl_isolation({"channels": {}}) is None

    def test_probe_blocks_when_isolation_off(self) -> None:
        from backend_ctl.mcp_driver_session import BackendUnavailable, DriverSession

        class OffDriver(FakeDriver):
            def introspect_router_stats(self, *a: Any, **k: Any) -> Any:
                return {"channels": {"backend_ctl": {"name": "backend_ctl", "session_isolation": False}}}

        ds = DriverSession(driver_factory=lambda: OffDriver(), log=lambda m: None, require_isolation=True)
        with pytest.raises(BackendUnavailable):
            ds.ensure()

    def test_probe_passes_when_isolation_on(self) -> None:
        from backend_ctl.mcp_driver_session import DriverSession

        class OnDriver(FakeDriver):
            def introspect_router_stats(self, *a: Any, **k: Any) -> Any:
                return {"channels": {"backend_ctl": {"name": "backend_ctl", "session_isolation": True}}}

        ds = DriverSession(driver_factory=lambda: OnDriver(), log=lambda m: None, require_isolation=True)
        assert ds.ensure() is not None

    def test_stdio_mode_skips_probe(self) -> None:
        from backend_ctl.mcp_driver_session import DriverSession

        called: List[bool] = []

        class OffDriver(FakeDriver):
            def introspect_router_stats(self, *a: Any, **k: Any) -> Any:
                called.append(True)
                return {"channels": {"backend_ctl": {"name": "backend_ctl", "session_isolation": False}}}

        # require_isolation по умолчанию False (stdio) → проба не выполняется даже при OFF
        ds = DriverSession(driver_factory=lambda: OffDriver(), log=lambda m: None)
        ds.ensure()
        assert called == []


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
