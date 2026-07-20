# -*- coding: utf-8 -*-
"""Task 3.2 — falsy-slice в rollback-журнале и byte-cap по умолчанию.

Две находки ultra-ревью:

1. ``register_rollback_log(limit=0)`` отдавал ВЕСЬ журнал вместо пустого: ``entries[-0:]``
   в Python — это ``entries[0:]``. Ту же ловушку в ``telemetry_history`` уже чинили, но
   правка не доехала до второго места.
2. Byte-cap был белым списком «тяжёлых» инструментов, то есть любой НОВЫЙ инструмент по
   умолчанию отдавал неограниченный объём (fail-open по размеру), а write-путь
   (audited-ветка) обходил потолок целиком — ``send_command('state.get_subtree')``
   заливал контекст агента.
"""

from __future__ import annotations

from typing import Any, Dict

from backend_ctl.mcp_tools import RESPONSE_BYTE_CAP, _UNCAPPED_TOOLS, _cap_heavy


# --- falsy-slice ---


def test_rollback_log_limit_zero_returns_empty() -> None:
    """``limit=0`` — это «последние 0 записей», а не «все»."""
    from backend_ctl.driver import BackendDriver

    drv = BackendDriver()
    for i in range(5):
        drv._rollback_journal.append({"commit_id": f"c{i}"})

    assert drv.register_rollback_log(limit=0)["entries"] == []
    assert len(drv.register_rollback_log(limit=2)["entries"]) == 2
    assert len(drv.register_rollback_log()["entries"]) == 5, "без limit — весь журнал"


def test_rollback_log_negative_limit_returns_empty() -> None:
    """Отрицательный limit — бессмыслица, но не повод отдать журнал целиком."""
    from backend_ctl.driver import BackendDriver

    drv = BackendDriver()
    drv._rollback_journal.append({"commit_id": "c0"})
    assert drv.register_rollback_log(limit=-1)["entries"] == []


# --- cap по умолчанию ---


def _huge() -> Dict[str, Any]:
    return {"success": True, "value": {f"путь.{i}": "x" * 100 for i in range(400)}}


def test_cap_applies_to_tools_not_on_the_allowlist() -> None:
    """Инструмент, о котором никто не думал, всё равно урезается (fail-closed по размеру)."""
    capped = _cap_heavy("какой_то_новый_инструмент", _huge(), {})
    assert capped["_truncated"] is True
    assert capped["_bytes"] > RESPONSE_BYTE_CAP


def test_full_true_still_bypasses_cap() -> None:
    """Явный ``full=true`` по-прежнему отдаёт полный объём — это осознанный запрос."""
    result = _cap_heavy("system_overview", _huge(), {"full": True})
    assert "_truncated" not in result


def test_small_responses_pass_through_untouched() -> None:
    """Малые ответы не трогаются: потолок — предохранитель, а не форматтер."""
    small = {"success": True, "status": "running"}
    assert _cap_heavy("get_status", small, {}) is small


def test_cursor_carrying_tools_are_never_capped() -> None:
    """events/events_page/register_snapshot усекать НЕЛЬЗЯ — это потеря данных.

    Курсор уже продвинулся: усечённые события не вернуть ничем, а у ``events_page``
    в ответе ещё и ``next_cursor`` — позиция читателя. Их объём ограничивается
    limit/max_items, а не байтовым потолком.
    """
    assert {"events", "events_page", "register_snapshot"} <= _UNCAPPED_TOOLS
    for name in ("events", "events_page", "register_snapshot"):
        result = _cap_heavy(name, _huge(), {})
        assert "_truncated" not in result, f"{name} обязан отдаваться целиком"


def test_audited_write_path_is_capped_too() -> None:
    """Write-путь больше не обходит потолок (в журнал при этом идёт полный результат)."""
    from backend_ctl.mcp_driver_session import DriverSession
    from backend_ctl.mcp_tools import dispatch_tool

    audited: list = []

    class _FakeDriver:
        connection_lost = False

        def export_subscriptions(self) -> list:
            return []

        def import_subscriptions(self, intents: list) -> None:
            pass

        def replay_subscriptions(self) -> list:
            return []

        def send_command(self, target: str, command: str, args: Any = None, **kw: Any) -> Dict[str, Any]:
            return _huge()

        def capabilities(self) -> Any:
            return None

        def close(self) -> None:
            pass

    session = DriverSession(driver_factory=_FakeDriver, log=lambda _m: None)
    session.record_audit = lambda *a, **kw: audited.append((a, kw))  # type: ignore[method-assign]

    out = dispatch_tool(session, "send_command", {"target": "ProcessManager", "command": "state.get_subtree"})

    assert out["_truncated"] is True, "ответ write-инструмента обязан урезаться"
    assert audited, "попытка обязана осесть в аудите"
    # В журнал уходит ПОЛНЫЙ результат: аудит обязан быть точным, усечение — только для агента.
    logged_result = audited[-1][1].get("result")
    assert logged_result is not None and "_truncated" not in logged_result
