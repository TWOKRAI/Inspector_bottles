# -*- coding: utf-8 -*-
"""Тесты Phase E «доверие» (E.1 аудит / E.2 валидация send_command / E.3 limits).

Сессия — реальная :class:`DriverSession` с fake-factory (detached driver вместо
сокета): проверяем session-aware диспетчеризацию сквозь :func:`dispatch_tool`, а не
внутренности хендлеров.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from backend_ctl.audit import AuditLog, resolve_audit_path
from backend_ctl.command_validate import validate_command_args
from backend_ctl.mcp_driver_session import DriverSession
from backend_ctl.mcp_tools import DEFAULT_HISTORY_LIMIT, RESPONSE_BYTE_CAP, dispatch_tool
from backend_ctl.protocol import Capabilities, ProcessCapabilities


# --------------------------------------------------------------------------- #
#  Fake driver                                                                #
# --------------------------------------------------------------------------- #


class _FakeDriver:
    """Пишет вызовы, отвечает JSON-совместимыми заглушками. Свод настраивается."""

    def __init__(self, caps: Capabilities | None = None) -> None:
        self.calls: List[Tuple[str, tuple, dict]] = []
        self._caps = caps or _caps(
            {
                "Cam": [
                    {
                        "name": "set_exposure",
                        "params_schema": [
                            {"name": "value", "type": "int", "required": True},
                            {"name": "roi", "type": "str", "required": False},
                        ],
                    },
                    {"name": "ping"},
                ]
            }
        )

    def capabilities(self, **kw: Any) -> Capabilities:
        self.calls.append(("capabilities", (), kw))
        return self._caps

    def set_register(self, *a: Any, **k: Any) -> Dict[str, Any]:
        self.calls.append(("set_register", a, k))
        return {"success": True}

    def send_command(self, *a: Any, **k: Any) -> Dict[str, Any]:
        self.calls.append(("send_command", a, k))
        return {"success": True, "echo": a}

    def system_overview(self, **k: Any) -> Dict[str, Any]:
        self.calls.append(("system_overview", (), k))
        return {"success": True, "processes": {f"p{i}": {"blob": "y" * 60} for i in range(400)}}

    def telemetry_history(self, path: str, limit: Any = None) -> Dict[str, Any]:
        self.calls.append(("telemetry_history", (path,), {"limit": limit}))
        n = limit if limit is not None else 9999
        return {"success": True, "points": [[i, i] for i in range(n)], "limit_used": limit}

    def get_status(self, *a: Any, **k: Any) -> Dict[str, Any]:
        self.calls.append(("get_status", a, k))
        return {"success": True}

    def introspect_status(self, *a: Any, **k: Any) -> Dict[str, Any]:
        return {"success": True}


def _caps(commands_by_proc: Dict[str, list], *, ok: bool = True) -> Capabilities:
    procs = {name: ProcessCapabilities(True, name, cmds, [], {}) for name, cmds in commands_by_proc.items()}
    return Capabilities(ok=ok, processes=procs, topology={}, channels=[])


@pytest.fixture
def session_factory(tmp_path, monkeypatch):
    """Фабрика (session, driver) с изолированным каталогом аудита во tmp."""
    monkeypatch.setenv("BACKEND_CTL_RECORD_DIR", str(tmp_path / "records"))

    def _make(caps: Capabilities | None = None) -> Tuple[DriverSession, _FakeDriver]:
        drv = _FakeDriver(caps)
        return DriverSession(driver_factory=lambda: drv), drv

    return _make


# --------------------------------------------------------------------------- #
#  E.1 — аудит-журнал мутаций                                                 #
# --------------------------------------------------------------------------- #


class TestAudit:
    def test_write_and_escalated_are_audited(self, session_factory) -> None:
        session, _ = session_factory()
        dispatch_tool(session, "set_register", {"process": "P", "register": "r", "field": "f", "value": 1})
        dispatch_tool(session, "send_command", {"target": "Cam", "command": "ping", "args": {}})
        log = session.read_audit()
        assert log["count"] == 2
        tools = [e["tool"] for e in log["entries"]]
        assert tools == ["set_register", "send_command"]
        assert all(e["ok"] for e in log["entries"])

    def test_read_tools_do_not_pollute_journal(self, session_factory) -> None:
        session, _ = session_factory()
        dispatch_tool(session, "get_status", {"process": "P"})
        dispatch_tool(session, "system_overview", {})
        assert session.read_audit()["count"] == 0

    def test_soft_failure_recorded_with_error(self, session_factory) -> None:
        session, drv = session_factory()
        drv.send_command = lambda *a, **k: {"success": False, "error": "нет такой команды"}  # type: ignore[method-assign]
        dispatch_tool(session, "send_command", {"target": "Cam", "command": "ping", "args": {}})
        entry = session.read_audit()["entries"][-1]
        assert entry["ok"] is False
        assert entry["error"] == "нет такой команды"

    def test_exception_recorded_then_reraised(self, session_factory) -> None:
        session, drv = session_factory()

        def _boom(*a: Any, **k: Any) -> Any:
            raise RuntimeError("сокет оборван")

        drv.set_register = _boom  # type: ignore[method-assign]
        with pytest.raises(RuntimeError):
            dispatch_tool(session, "set_register", {"process": "P", "register": "r", "field": "f", "value": 1})
        entry = session.read_audit()["entries"][-1]
        assert entry["ok"] is False
        assert "сокет оборван" in entry["error"]

    def test_session_log_tool_returns_tail(self, session_factory) -> None:
        session, _ = session_factory()
        for i in range(3):
            dispatch_tool(session, "set_register", {"process": "P", "register": "r", "field": f"f{i}", "value": i})
        res = dispatch_tool(session, "session_log", {"limit": 2})
        assert res["success"] is True
        assert res["count"] == 2
        assert res["entries"][-1]["args"]["field"] == "f2"

    def test_durable_jsonl_written(self, session_factory, tmp_path) -> None:
        session, _ = session_factory()
        dispatch_tool(session, "set_register", {"process": "P", "register": "r", "field": "f", "value": 1})
        path = Path(resolve_audit_path())
        assert path.exists()
        lines = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        assert lines and lines[-1]["tool"] == "set_register"

    def test_read_only_session_creates_no_file(self, session_factory) -> None:
        session, _ = session_factory()
        dispatch_tool(session, "get_status", {"process": "P"})
        assert not Path(resolve_audit_path()).exists()

    def test_ring_bounded(self) -> None:
        log = AuditLog(path="/dev/null", ring=3)
        for i in range(5):
            log.record("set_register", "write", {"i": i}, result={"success": True})
        assert [e["args"]["i"] for e in log.records()] == [2, 3, 4]


# --------------------------------------------------------------------------- #
#  E.2 — клиентская валидация send_command                                    #
# --------------------------------------------------------------------------- #


class TestSendCommandValidation:
    def test_unknown_target_blocked_before_send(self, session_factory) -> None:
        session, drv = session_factory()
        res = dispatch_tool(session, "send_command", {"target": "Nope", "command": "x", "args": {}})
        assert res["validation"] is True
        assert "не найден" in res["error"]
        assert not any(c[0] == "send_command" for c in drv.calls)

    def test_missing_required_field_blocked(self, session_factory) -> None:
        session, drv = session_factory()
        res = dispatch_tool(session, "send_command", {"target": "Cam", "command": "set_exposure", "args": {"roi": "a"}})
        assert res["validation"] is True
        assert "value" in res["error"]
        assert not any(c[0] == "send_command" for c in drv.calls)

    def test_valid_args_pass_through(self, session_factory) -> None:
        session, drv = session_factory()
        res = dispatch_tool(session, "send_command", {"target": "Cam", "command": "set_exposure", "args": {"value": 5}})
        assert res["success"] is True
        assert any(c[0] == "send_command" for c in drv.calls)

    def test_command_without_schema_passes(self, session_factory) -> None:
        session, drv = session_factory()
        res = dispatch_tool(session, "send_command", {"target": "Cam", "command": "ping", "args": {}})
        assert res["success"] is True
        assert any(c[0] == "send_command" for c in drv.calls)

    def test_unknown_command_on_known_target_passes(self, session_factory) -> None:
        """Незаявленная команда известного процесса — не блок (карточка может быть неполной)."""
        session, drv = session_factory()
        res = dispatch_tool(session, "send_command", {"target": "Cam", "command": "dynamic_thing", "args": {}})
        assert res.get("validation") is None
        assert any(c[0] == "send_command" for c in drv.calls)

    def test_degraded_snapshot_does_not_block(self, session_factory) -> None:
        """Свод ok=False (карточка не собралась) → не блокируем по отсутствию адресата."""
        caps = _caps({"Cam": []}, ok=False)
        session, drv = session_factory(caps)
        res = dispatch_tool(session, "send_command", {"target": "Ghost", "command": "x", "args": {}})
        assert res.get("validation") is None
        assert any(c[0] == "send_command" for c in drv.calls)

    def test_capabilities_cached_across_calls(self, session_factory) -> None:
        session, drv = session_factory()
        for _ in range(3):
            dispatch_tool(session, "send_command", {"target": "Cam", "command": "ping", "args": {}})
        assert sum(1 for c in drv.calls if c[0] == "capabilities") == 1

    def test_blocked_attempt_is_audited(self, session_factory) -> None:
        session, _ = session_factory()
        dispatch_tool(session, "send_command", {"target": "Nope", "command": "x", "args": {}})
        entry = session.read_audit()["entries"][-1]
        assert entry["tool"] == "send_command"
        assert entry["ok"] is False


class TestValidatorPure:
    def test_missing_required_lists_field_and_schema(self) -> None:
        caps = _caps({"Cam": [{"name": "c", "params_schema": [{"name": "v", "required": True}]}]})
        err = validate_command_args(caps, "Cam", "c", {})
        assert err is not None and "v" in err

    def test_all_required_present_ok(self) -> None:
        caps = _caps({"Cam": [{"name": "c", "params_schema": [{"name": "v", "required": True}]}]})
        assert validate_command_args(caps, "Cam", "c", {"v": 1}) is None

    def test_none_caps_passes(self) -> None:
        assert validate_command_args(None, "Cam", "c", {}) is None


# --------------------------------------------------------------------------- #
#  E.3 — response limits                                                      #
# --------------------------------------------------------------------------- #


class TestResponseLimits:
    def test_telemetry_history_default_limit(self, session_factory) -> None:
        session, _ = session_factory()
        res = dispatch_tool(session, "telemetry_history", {"path": "a"})
        assert res["limit_used"] == DEFAULT_HISTORY_LIMIT

    def test_telemetry_history_explicit_limit_overrides(self, session_factory) -> None:
        session, _ = session_factory()
        res = dispatch_tool(session, "telemetry_history", {"path": "a", "limit": 500})
        assert res["limit_used"] == 500

    def test_telemetry_history_full_removes_cap(self, session_factory) -> None:
        session, _ = session_factory()
        res = dispatch_tool(session, "telemetry_history", {"path": "a", "full": True})
        assert res["limit_used"] is None

    def test_subtree_truncated_to_shape_map(self, session_factory) -> None:
        session, drv = session_factory()
        drv.send_command = lambda *a, **k: {  # type: ignore[method-assign]
            "success": True,
            **{f"k{i}": "z" * 80 for i in range(400)},
        }
        res = dispatch_tool(session, "state_get_subtree", {"path": ""})
        assert res["_truncated"] is True
        assert res["_bytes"] > RESPONSE_BYTE_CAP
        assert "keys" in res

    def test_subtree_full_bypasses_cap(self, session_factory) -> None:
        session, drv = session_factory()
        drv.send_command = lambda *a, **k: {  # type: ignore[method-assign]
            "success": True,
            **{f"k{i}": "z" * 80 for i in range(400)},
        }
        res = dispatch_tool(session, "state_get_subtree", {"path": "", "full": True})
        assert "_truncated" not in res
        assert "k0" in res

    def test_small_response_untouched(self, session_factory) -> None:
        session, drv = session_factory()
        drv.send_command = lambda *a, **k: {"success": True, "small": 1}  # type: ignore[method-assign]
        res = dispatch_tool(session, "state_get_subtree", {"path": "x"})
        assert res == {"success": True, "small": 1}

    def test_system_overview_truncated_when_huge(self, session_factory) -> None:
        session, _ = session_factory()
        res = dispatch_tool(session, "system_overview", {})
        assert res["_truncated"] is True
        assert "processes" in res["keys"]
