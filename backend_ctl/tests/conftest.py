# -*- coding: utf-8 -*-
"""Фикстуры backend_ctl-тестов: headless-бэкенд на BackendHarness (Ф1 Task 1.3).

``headless_backend`` поднимает реальную систему прототипа БЕЗ gui (honest headless),
отдаёт подключённый ``BackendDriver`` и гарантированно гасит систему в teardown
(watchdog + kill поддерева) — висящих процессов после теста не остаётся.

Session-scope: старт/стоп системы дорогой (~секунды), поэтому один бэкенд на все
harness-тесты модуля. Тесты только читают состояние — общий инстанс безопасен.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import pytest

from backend_ctl.harness import BackendHarness


def wire_line(msg: Dict[str, Any]) -> bytes:
    """Собрать проводную строку push'а так же, как её видит reader-поток.

    Общий хелпер unit-тестов событийного контура (инжекция через dispatch_raw) —
    одна точка правды о wire-кодировке вместо копий по тест-файлам.
    """
    return json.dumps(msg, ensure_ascii=False).encode("utf-8")


#: Счётчики router'а, которые он инициализирует при старте и потому обязан
#: отдавать всегда. Порядок — как в ``RouterStats.from_response``.
ROUTER_COUNTERS = (
    "sent_ok",
    "received",
    "middleware_dropped",
    "errors",
    "sent_attempted",
    "sent_via_channel",
    "sent_via_targets",
    "queued_async",
    "send_queue_size",
    "queue_data_evicted",
    "queue_system_evict_blocked",
    "frame_loans_released_on_evict",
    # Ф4 Task 4.3: безвозвратные потери never-drop груза (раньше только в stdlib-логе).
    "queue_never_drop_loss_total",
    # Мапа, не счётчик — но в ``missing`` попадает так же, поэтому в списке порядка есть.
    "queue_senders",
)


def full_router_stats(**overrides: Any) -> Dict[str, Any]:
    """Полная секция ``router_stats`` для подставных ответов.

    Одна точка правды о составе счётчиков: обёртка судит форму ответа по
    ``missing``, поэтому фикстура с четырьмя ключами проверяла бы не тот
    контракт — «здоровый» ответ выглядел бы как расхождение формы.
    Точечные ключи разбивки по kind сюда не входят (заводятся на лету).
    """
    stats: Dict[str, Any] = {name: 0 for name in ROUTER_COUNTERS}
    # Ф4 Task 4.3: секция «кто душит очередь» — мапа, а не счётчик (пустая = трафика
    # не было; отсутствие ключа = сборка без учёта, что честно попадает в missing).
    stats["queue_senders"] = {}
    stats.update({"sent_ok": 10, "received": 20})
    stats.update(overrides)
    return stats


def page_events(drv, cursor: Any = None, *, plane: Any = None, limit: int = 200):
    """Одна страница ``events_page`` → (сырые event-dict'ы, next_cursor).

    Тонкий адаптер миграции с legacy-дренажа ``events()`` (F.1, удалён): вызывающий
    держит ``cursor`` во внешнем цикле между вызовами (как раньше держал неявно сам
    driver в ``_drain_seq``), здесь — только чтение одной страницы. ``reset_required``
    (курсор чужого поколения — например после реконнекта в другом тесте модуля)
    обрабатывается один раз прозрачно: страница перечитывается с ``cursor=None``.
    """
    page = drv.events_page(plane, cursor=cursor, limit=limit)
    if not page.get("success", True):
        page = drv.events_page(plane, cursor=None, limit=limit)
    events = [it["event"] for it in page.get("items", [])]
    return events, page.get("next_cursor")


def wait_for_events(drv, cursor: Any = None, *, plane: Any = None, timeout: float = 2.0, limit: int = 200):
    """Дождаться хотя бы одного события плоскости (events_page-поллинг, не дольше timeout).

    Заменяет legacy блокирующее ``events(timeout=N)`` (удалено в F.1): events_page
    неблокирующий, поэтому ждём коротким поллингом. Молчание за timeout — пустой
    список (симметрично прежнему таймаут-поведению drain'а).
    """
    deadline = time.monotonic() + timeout
    evts, cursor = page_events(drv, cursor, plane=plane, limit=limit)
    while not evts and time.monotonic() < deadline:
        time.sleep(0.02)
        evts, cursor = page_events(drv, cursor, plane=plane, limit=limit)
    return evts, cursor


def bookmark_cursor(drv, *, plane: Any = None):
    """Курсор «хвост сейчас» плоскости — эквивалент legacy ``drv.events()  # осушить``.

    Прыжок к текущему хвосту без чтения backlog'а: то же намерение, что было у
    вызова-дренажа «слить накопленное перед провокацией», но недеструктивно —
    других читателей той же плоскости не затрагивает.
    """
    return drv.events_page(plane)["bookmark"]


@pytest.fixture(scope="session")
def headless_backend():
    """Подключённый BackendDriver к headless-системе прототипа (без gui).

    with_base=True — подмешиваем фундамент (там объявлен gui), чтобы strip_gui реально
    его исключил: доказываем честный headless на топологии, которая иначе спавнит Qt.
    """
    harness = BackendHarness(with_base=True)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()
