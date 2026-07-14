# -*- coding: utf-8 -*-
"""Ф7 G.5.c — PipelineExecutor дропает батч на устаревшем zero-copy view.

Между _execute_chain и _send_results: если входной view не пережил обработку
(middleware.frame_view_valid → False), результат НЕ отправляется (построен на
порванных пикселях). На не-view пути (нет _frame_is_view) — ноль оверхеда.
"""

from __future__ import annotations

import queue
import threading
import time

from multiprocess_framework.modules.process_module.generic.pipeline_executor import (
    PipelineExecutor,
)


class _FakeShm:
    """Минимальный middleware: frame_view_valid возвращает заданное, считает вызовы."""

    def __init__(self, valid: bool):
        self._valid = valid
        self.calls: list[tuple[str, int]] = []

    def frame_view_valid(self, name: str, gen: int) -> bool:
        self.calls.append((name, gen))
        return self._valid


def _make_executor(shm, sent: list):
    return PipelineExecutor(
        plugins=[],  # пустая цепочка = passthrough (items наружу без изменений)
        chain_targets=["out"],
        shm_middleware=shm,
        send_fn=lambda target, msg: sent.append(msg),  # _send(target, msg)
    )


class TestCollectAndValidate:
    def test_collect_only_view_items(self):
        ex = _make_executor(_FakeShm(True), [])
        items = [
            {"_frame_is_view": True, "_shm_view_name": "seg0", "_shm_view_generation": 4},
            {"frame": "plain"},  # не view — игнор
            {"_frame_is_view": True, "_shm_view_name": "seg1", "_shm_view_generation": 6},
        ]
        assert ex._collect_view_checks(items) == [("seg0", 4), ("seg1", 6)]

    def test_no_middleware_no_checks(self):
        ex = _make_executor(None, [])
        assert ex._collect_view_checks([{"_frame_is_view": True, "_shm_view_name": "x"}]) == []

    def test_all_valid_true_any_stale_false(self):
        ex_ok = _make_executor(_FakeShm(True), [])
        assert ex_ok._frame_views_valid([("seg0", 4), ("seg1", 6)]) is True
        ex_bad = _make_executor(_FakeShm(False), [])
        assert ex_bad._frame_views_valid([("seg0", 4)]) is False


class TestRunLoopDrop:
    def _run_one_batch(self, ex, batch):
        q: queue.Queue = queue.Queue()
        q.put(batch)
        ex.bind_queue(q)
        stop = threading.Event()
        pause = threading.Event()
        t = threading.Thread(target=ex.run, args=(stop, pause))
        t.start()
        time.sleep(0.15)
        stop.set()
        t.join(timeout=1)

    def test_stale_view_batch_not_sent(self):
        sent: list = []
        shm = _FakeShm(valid=False)  # view устарел
        ex = _make_executor(shm, sent)
        self._run_one_batch(ex, [{"_frame_is_view": True, "_shm_view_name": "seg0", "_shm_view_generation": 2}])
        assert sent == []  # дропнут, не отправлен
        assert shm.calls  # re-check был вызван

    def test_valid_view_batch_sent(self):
        sent: list = []
        shm = _FakeShm(valid=True)
        ex = _make_executor(shm, sent)
        self._run_one_batch(ex, [{"_frame_is_view": True, "_shm_view_name": "seg0", "_shm_view_generation": 2}])
        assert len(sent) == 1  # валиден → отправлен
        assert sent[0]["data"]["_shm_view_name"] == "seg0"

    def test_non_view_batch_sent_without_recheck(self):
        sent: list = []
        shm = _FakeShm(valid=False)  # даже если бы дёрнули — False; но не view → не дёргаем
        ex = _make_executor(shm, sent)
        self._run_one_batch(ex, [{"frame": "plain", "camera_id": 1}])
        assert len(sent) == 1  # обычный кадр уходит
        assert shm.calls == []  # re-check НЕ вызывался (ноль оверхеда на не-view пути)
