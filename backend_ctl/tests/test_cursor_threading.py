# -*- coding: utf-8 -*-
"""Task 2.3 — курсоры инструментов под локом + единый retry-цикл.

Находка ultra-ревью: приватные курсоры ``_events_tool_cursor`` (мост MCP-инструмента
``events``) и ``_obs_records_cursor`` (наблюдательный дефолт ``observability_records``)
читались, продвигались и записывались тремя отдельными шагами, а ``tools/call`` идут в
параллельных потоках SDK. Итог check-then-act: два вызова читают ОДИН курсор, оба
получают одну страницу (события дублируются), затем младший перезаписывает старший —
и часть событий не увидит никто.

Вторая половина задачи — дедуп: retry-цикл на ``reset_required`` жил двумя копиями
(в ``mcp_tools._events`` и в ``driver.observability_records``), и правка в одной молча
не доезжала до второй.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from backend_ctl.events import page_with_reset_retry


class _PagingDriver:
    """Driver-заглушка с ОДНОЙ лентой: каждая страница выдаётся ровно один раз.

    Отдаёт события по курсору-счётчику и намеренно делает паузу между чтением и
    выдачей — так окно гонки шире планировщика, иначе GIL прячет check-then-act и
    тест зеленел бы на непотокобезопасном коде.
    """

    def __init__(self, total: int = 200, page_size: int = 10) -> None:
        self._total = total
        self._page_size = page_size
        self._tool_cursor_lock = threading.Lock()
        self._events_tool_cursor: Any = None
        self._obs_records_cursor: Any = None

    def events_page(self, plane: Any = None, *, cursor: Any = None, limit: Any = None) -> Dict[str, Any]:
        start = int(cursor) if cursor is not None else 0
        # Пауза ВНУТРИ страницы: имитирует реальный обход кольца, растягивая окно
        # между «прочитал курсор» и «записал новый».
        threading.Event().wait(0.001)
        end = min(start + self._page_size, self._total)
        items = [{"event": {"seq": i}} for i in range(start, end)]
        # next_cursor — ВСЕГДА позиция хвоста, как у настоящего EventHub. Отдавать
        # None в конце ленты нельзя: None означает «читай с начала», и опрос уходил бы
        # на второй круг вечно.
        return {"success": True, "items": items, "next_cursor": end}


def _drain_via_tool(drv: _PagingDriver, collected: List[int], lock: threading.Lock) -> None:
    """Слепок логики моста ``events``: триплет чтения курсора под локом driver'а."""
    while True:
        with drv._tool_cursor_lock:
            cursor = drv._events_tool_cursor
            page = page_with_reset_retry(lambda c: drv.events_page(cursor=c), cursor)
            drv._events_tool_cursor = page.get("next_cursor", cursor)
        items = [it["event"]["seq"] for it in page.get("items", [])]
        if not items:
            return  # лента исчерпана — пустая страница есть сигнал конца
        with lock:
            collected.extend(items)


def test_parallel_events_never_deliver_a_page_twice() -> None:
    """Параллельные чтения делят ленту без дублей и без пропусков."""
    drv = _PagingDriver(total=200, page_size=10)
    collected: List[int] = []
    guard = threading.Lock()

    threads = [threading.Thread(target=_drain_via_tool, args=(drv, collected, guard)) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)
    assert not [t for t in threads if t.is_alive()], "поток завис — вероятен дедлок на локе курсоров"

    assert len(collected) == len(set(collected)), "события продублировались между потоками"
    assert sorted(collected) == list(range(200)), "часть событий не увидел никто (курсор затёрт)"


# --- Единый retry-хелпер ---


def test_reset_retry_rereads_from_scratch_when_no_resume_cursor() -> None:
    """reset_required без подсказки сервера → перечитать с начала кольца."""
    calls: List[Any] = []

    def _page(cursor: Any) -> Dict[str, Any]:
        calls.append(cursor)
        if cursor == "старый@gen1":
            return {"success": False, "error": "reset_required"}
        return {"success": True, "items": [], "next_cursor": "новый@gen2"}

    page = page_with_reset_retry(_page, "старый@gen1")

    assert page["success"] is True
    assert calls == ["старый@gen1", None], "после сброса обязано быть перечитывание"


def test_reset_retry_prefers_resume_cursor_when_server_names_it() -> None:
    """Если сервер назвал границу новой инкарнации — идём с неё, а не с начала.

    Это задел под Task 2.4: перечитывание с ``None`` отдаёт весь доступный ринг заново,
    то есть дублирует агенту всё, что он уже видел до рестарта.
    """
    calls: List[Any] = []

    def _page(cursor: Any) -> Dict[str, Any]:
        calls.append(cursor)
        if cursor == "старый@gen1":
            return {"success": False, "error": "reset_required", "resume_cursor": "all:0@gen2"}
        return {"success": True, "items": [], "next_cursor": "all:5@gen2"}

    page_with_reset_retry(_page, "старый@gen1")

    assert calls == ["старый@gen1", "all:0@gen2"], "resume_cursor обязан иметь приоритет над None"


def test_single_retry_implementation_is_shared() -> None:
    """Оба call-site используют общий хелпер — копий retry-цикла не осталось.

    Структурная проверка: раньше одинаковый цикл жил в двух местах и расходился.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for name in ("driver.py", "mcp_tools.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "page_with_reset_retry" in src, f"{name} обязан использовать общий хелпер"
