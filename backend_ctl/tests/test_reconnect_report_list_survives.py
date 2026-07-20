# -*- coding: utf-8 -*-
"""Task 1.3 — reconnect-report не теряется на list-результатах инструмента.

До фикса ``pop_reconnect_report()`` вызывался в ``call_tool`` безусловно, а вливался
в ответ только под ``isinstance(result, dict)``. Инструмент, вернувший ``list``
(например ``events``), тем не менее СЪЕДАЛ одноразовый отчёт этим безусловным pop'ом —
агент никогда не узнавал, что был реконнект и durable-подписки переигрывались, если
между реконнектом и следующим dict-ответом затесался хотя бы один list-вызов.

Юнит на fake-driver (без сокетов/harness) — здесь важна только логика merge внутри
``SDKToolServer.call_tool``, а не механика самого реконнекта (её live-доказательство —
``test_reconnect_recovery_live.py``, Task 1.1). Наличие ожидающего отчёта симулируется
напрямую через ``DriverSession._note_report`` — тем же путём, которым его реально
кладёт ``DriverSession.ensure()`` после restore durable-подписок.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional

import pytest

from backend_ctl.mcp_server_sdk import SDKToolServer

pytest.importorskip("mcp", reason="SDKToolServer требует опциональный extra 'ctl' (пакет mcp)")


class _FakeDriver:
    """Минимальный driver: durable-подписка (dict) + курсорный дренаж событий (list)."""

    def __init__(self) -> None:
        self.closed = False
        self._events_tool_cursor: Optional[str] = None
        # Часть контракта driver'а с Task 2.3: мост events берёт этот лок вокруг
        # триплета «прочитал курсор → взял страницу → записал». Fake обязан его иметь —
        # делать код терпимым к его отсутствию нельзя, это молча вернуло бы гонку.
        self._tool_cursor_lock = threading.Lock()

    def export_subscriptions(self) -> List[Dict[str, Any]]:
        return []

    def close(self) -> None:
        self.closed = True

    def state_subscribe(self, pattern: str, **_kw: Any) -> Dict[str, Any]:
        return {"success": True, "pattern": pattern}

    def events_page(self, plane: Any = None, *, cursor: Any = None, limit: Any = None) -> Dict[str, Any]:
        # Пустая, но валидная страница — _events() инструмент отдаёт [] и не зацикливается
        # (в тесте timeout не передаётся, deadline=None → один проход).
        return {"success": True, "items": [], "next_cursor": cursor}


def _make_server() -> SDKToolServer:
    return SDKToolServer(driver_factory=lambda: _FakeDriver(), log=lambda _m: None)


def _pending_report(server: SDKToolServer) -> Optional[Dict[str, Any]]:
    """Заглянуть в ожидающий отчёт БЕЗ pop'а (белый ящик — проверка «ещё не съеден»)."""
    return server._session._reconnect_report  # noqa: SLF001 — намеренный белый ящик теста


def test_list_result_does_not_consume_pending_reconnect_report() -> None:
    """list-инструмент (events) не должен трогать одноразовый отчёт вообще."""
    server = _make_server()
    # Симулируем состояние «реконнект только что случился» — тем же вызовом, которым
    # его реально кладёт DriverSession.ensure() после replay durable-подписок.
    server._session._note_report(  # noqa: SLF001 — намеренный белый ящик теста
        reconnected=True,
        resubscribed=[{"command": "state.subscribe", "target": "ProcessManager", "success": True}],
    )

    result = server.call_tool("events", {})
    assert isinstance(result, list) and result, f"events должен вернуть успешный список контента: {result!r}"
    events_payload = json.loads(result[0].text)
    assert events_payload == [], "events на пустой fake-странице должен отдать пустой список"

    # Главная проверка Task 1.3: list-ответ НЕ обнулил отчёт — он всё ещё ждёт dict-вызова.
    assert _pending_report(server) is not None, "list-результат не должен съедать reconnect-report"


def test_next_dict_call_carries_report_exactly_once() -> None:
    """Следующий dict-вызов после list несёт отчёт РОВНО один раз; третий — уже без него."""
    server = _make_server()
    server._session._note_report(  # noqa: SLF001 — намеренный белый ящик теста
        reconnected=True,
        resubscribed=[{"command": "state.subscribe", "target": "ProcessManager", "success": True}],
    )

    # 1. list-вызов — отчёт переживает (см. test выше).
    server.call_tool("events", {})
    assert _pending_report(server) is not None

    # 2. Первый dict-вызов ПОСЛЕ list-а — отчёт вливается сюда и только сюда.
    first = json.loads(server.call_tool("state_subscribe", {"pattern": "processes.**"})[0].text)
    assert first.get("success") is True
    assert first.get("reconnected") is True, first
    assert first.get("resubscribed"), first
    assert _pending_report(server) is None, "dict-вызов обязан забрать (pop) отчёт"

    # 3. Второй dict-вызов подряд — отчёт уже отдан, повторно не всплывает.
    second = json.loads(server.call_tool("state_subscribe", {"pattern": "processes.**"})[0].text)
    assert second.get("success") is True
    assert "reconnected" not in second, second
    assert "resubscribed" not in second, second
