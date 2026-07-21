# -*- coding: utf-8 -*-
"""Ф7 G.5.d-2 — owner-handler shm_release в GenericProcess делегирует в middleware."""

from __future__ import annotations

from multiprocess_framework.modules.process_module.generic.generic_process import (
    GenericProcess,
)


class _FakeMw:
    def __init__(self):
        self.released: list = []
        self.reclaimed: list = []
        self.evicted_flags: list = []

    def release_slots(self, releases, evicted: bool = False):
        self.released.append(releases)
        self.evicted_flags.append(evicted)

    def reclaim_reader(self, dead_reader):
        self.reclaimed.append(dead_reader)


def _bare_process():
    """GenericProcess без тяжёлой инициализации — только поля, нужные хендлеру."""
    gp = GenericProcess.__new__(GenericProcess)
    gp.name = "cam0"
    gp._log_error = lambda m: None
    return gp


def test_handler_delegates_releases_to_middleware():
    gp = _bare_process()
    mw = _FakeMw()
    gp._handle_shm_release({"data": {"releases": [{"index": 0, "generation": 2, "reader": "c0"}]}}, mw)
    assert mw.released == [[{"index": 0, "generation": 2, "reader": "c0"}]]
    assert mw.evicted_flags == [False]  # штатный release (не вытеснение)


def test_handler_passes_evicted_flag():
    """LIVE-2: конверт вытеснения (data.evicted=True) → release_slots(evicted=True)."""
    gp = _bare_process()
    mw = _FakeMw()
    gp._handle_shm_release(
        {"data": {"evicted": True, "releases": [{"slot": "s", "index": 1, "generation": -1, "reader": "lines"}]}},
        mw,
    )
    assert mw.released == [[{"slot": "s", "index": 1, "generation": -1, "reader": "lines"}]]
    assert mw.evicted_flags == [True]


def test_handler_ignores_empty_and_malformed():
    gp = _bare_process()
    mw = _FakeMw()
    gp._handle_shm_release({"data": {"releases": []}}, mw)  # пусто
    gp._handle_shm_release({}, mw)  # нет data
    gp._handle_shm_release("garbage", mw)  # не dict
    gp._handle_shm_release({"data": {}}, mw)  # нет releases
    assert mw.released == []  # ни один не дошёл до release_slots


def test_reclaim_handler_delegates():
    gp = _bare_process()
    mw = _FakeMw()
    gp._handle_shm_reclaim({"data": {"dead_reader": "consumer_x"}}, mw)
    assert mw.reclaimed == ["consumer_x"]


def test_reclaim_handler_ignores_malformed():
    gp = _bare_process()
    mw = _FakeMw()
    gp._handle_shm_reclaim({"data": {"dead_reader": ""}}, mw)  # пусто
    gp._handle_shm_reclaim({}, mw)  # нет data
    gp._handle_shm_reclaim("garbage", mw)  # не dict
    assert mw.reclaimed == []


def test_shm_release_routes_to_system_queue():
    """Ревью-фикс 16: shm_release с queue_type=system → system-очередь (её поллит
    SystemThreads→event_dispatcher→handler). БЕЗ queue_type type=shm_release ушёл бы в
    data-очередь (DataReceiver), release не доставился бы никогда."""
    from multiprocess_framework.modules.router_module.core.router_manager import (
        RouterManager,
    )

    # Как формирует конверт _flush_releases (ревью-фикс 16).
    assert RouterManager._select_queue_type({"type": "shm_release", "queue_type": "system"}) == "system"
    # Доказательство исходного бага: без queue_type — data-очередь (недоставка).
    assert RouterManager._select_queue_type({"type": "shm_release"}) == "data"
