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

    def release_slots(self, releases):
        self.released.append(releases)

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
