# -*- coding: utf-8 -*-
"""Ф7 G.8: IdleWorker.is_busy — busy-маркер вокруг полезной нагрузки цикла (кадра).

is_busy=True только во время _do_work (drain-контур этого дожидается перед detach/stop)."""

from __future__ import annotations

import threading

from multiprocess_framework.modules.process_module.generic.idle_worker import IdleWorker


def test_is_busy_true_during_do_work_false_otherwise():
    seen = {}

    class _W(IdleWorker):
        def _do_work(self) -> None:
            seen["busy_during"] = self.is_busy

    w = _W(config={"execution_mode": "task", "target_interval_ms": 1})
    assert w.is_busy is False  # до старта — не busy
    stop, pause = threading.Event(), threading.Event()
    w.run(stop, pause)  # task-режим → один _run_once
    assert seen["busy_during"] is True  # во время кадра — busy
    assert w.is_busy is False  # после — снят (finally)


def test_is_busy_cleared_even_on_do_work_exception():
    class _W(IdleWorker):
        def _do_work(self) -> None:
            raise RuntimeError("boom")

    w = _W(config={"execution_mode": "task"})
    stop, pause = threading.Event(), threading.Event()
    try:
        w.run(stop, pause)
    except RuntimeError:
        pass
    assert w.is_busy is False  # busy снят через finally даже при исключении
