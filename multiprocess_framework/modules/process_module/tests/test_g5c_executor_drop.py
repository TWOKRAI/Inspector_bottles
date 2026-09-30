# -*- coding: utf-8 -*-
"""Ф7 G.5.c — PipelineExecutor дропает батч на устаревшем zero-copy view.

Между _execute_chain и _send_results: если входной view не пережил обработку
(middleware.frame_view_valid → False), результат НЕ отправляется (построен на
порванных пикселях). На не-view пути (нет _shm_views) — ноль оверхеда.
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

    def frame_view_valid(self, ref: dict) -> bool:
        self.calls.append((ref["name"], ref["gen"]))
        return self._valid


def _ref(owner: str, idx: int, gen: int, name: str | None = None) -> dict:
    """Ссылка SHM (Task 4.4): она же билет re-check/release."""
    return {"owner": owner, "slot": "output_frames", "idx": idx, "gen": gen, "name": name or f"v{idx}"}


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
        ref0, ref1 = _ref("cam0", 0, 4, "seg0"), _ref("cam1", 1, 6, "seg1")
        items = [
            {"_shm_views": [ref0]},
            {"frame": "plain"},  # не view — игнор
            {"_shm_views": [ref1]},
        ]
        assert ex._collect_view_tickets(items) == [ref0, ref1]

    def test_no_middleware_no_checks(self):
        ex = _make_executor(None, [])
        assert ex._collect_view_tickets([{"_shm_views": [_ref("cam0", 0, 2, "x")]}]) == []

    def test_all_valid_true_any_stale_false(self):
        ex_ok = _make_executor(_FakeShm(True), [])
        assert ex_ok._frame_views_valid([_ref("cam0", 0, 4, "seg0")]) is True
        ex_bad = _make_executor(_FakeShm(False), [])
        assert ex_bad._frame_views_valid([_ref("cam0", 0, 4, "seg0")]) is False


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
        self._run_one_batch(ex, [{"_shm_views": [_ref("cam0", 0, 2, "seg0")]}])
        assert sent == []  # дропнут, не отправлен
        assert shm.calls  # re-check был вызван

    def test_valid_view_batch_sent(self):
        sent: list = []
        shm = _FakeShm(valid=True)
        ex = _make_executor(shm, sent)
        self._run_one_batch(ex, [{"_shm_views": [_ref("cam0", 0, 2, "seg0")], "marker": 7}])
        assert len(sent) == 1  # валиден → отправлен
        assert sent[0]["data"]["marker"] == 7

    def test_non_view_batch_sent_without_recheck(self):
        sent: list = []
        shm = _FakeShm(valid=False)  # даже если бы дёрнули — False; но не view → не дёргаем
        ex = _make_executor(shm, sent)
        self._run_one_batch(ex, [{"frame": "plain", "camera_id": 1}])
        assert len(sent) == 1  # обычный кадр уходит
        assert shm.calls == []  # re-check НЕ вызывался (ноль оверхеда на не-view пути)


def _view_item(owner, idx, gen):
    return {"_shm_views": [_ref(owner, idx, gen)]}


class TestReleaseAccumulation:
    """G.5.d-2: executor копит release-тикеты и флашит пачкой владельцу (не на per-frame)."""

    @staticmethod
    def _executor(sent):
        shm = _FakeShm(valid=True)
        shm.loan_protocol_enabled = True  # публичный контракт (ревью-фикс 13)
        shm.ring_depth = 10  # ревью-фикс 6: порог = min(threshold, ring_depth)
        return PipelineExecutor(
            plugins=[],
            chain_targets=["out"],
            shm_middleware=shm,
            send_fn=lambda target, msg: sent.append((target, msg)),
        )

    def test_accumulate_then_flush_on_threshold(self):
        sent: list = []
        ex = self._executor(sent)
        ex._release_batch_threshold = 3
        ex._accumulate_releases([_ticket("cam0", 0, 2), _ticket("cam0", 1, 2)])
        assert sent == []  # < порога — не флашим
        ex._accumulate_releases([_ticket("cam0", 2, 2)])
        assert len(sent) == 1  # порог 3 достигнут → флаш
        target, msg = sent[0]
        assert target == "cam0"
        # ревью-фикс 16: queue_type="system" (не channel) — иначе уходит в data-очередь.
        assert msg["type"] == "shm_release" and msg["queue_type"] == "system"
        assert len(msg["data"]["releases"]) == 3
        assert msg["data"]["releases"][0]["reader"] == ex._node

    def test_threshold_capped_by_ring_depth(self):
        """Ревью-фикс 6: порог не выше глубины кольца (иначе тикеты голодают)."""
        sent: list = []
        ex = self._executor(sent)
        ex._shm.ring_depth = 3  # мелкое кольцо
        ex._release_batch_threshold = 8  # хотели 8, но кольцо 3
        ex._accumulate_releases([_ticket("cam0", i, 2) for i in range(3)])
        assert len(sent) == 1  # флаш на 3 (=ring_depth), не ждём 8

    def test_no_accumulate_without_loan_protocol(self):
        sent: list = []
        shm = _FakeShm(valid=True)  # loan_protocol_enabled не выставлен → getattr False
        ex = PipelineExecutor(
            plugins=[], chain_targets=["out"], shm_middleware=shm, send_fn=lambda t, m: sent.append((t, m))
        )
        ex._accumulate_releases([_ticket("cam0", 0, 2)])
        assert ex._pending_release_count == 0

    def test_run_loop_flushes_residual_on_stop(self):
        sent: list = []
        ex = self._executor(sent)
        ex._release_batch_threshold = 100  # не флашить по порогу — только на стопе
        TestRunLoopDrop()._run_one_batch(ex, [_view_item("cam0", 0, 5)])
        releases = [m for _, m in sent if m.get("type") == "shm_release"]
        assert len(releases) == 1  # хвост флашнут на остановке воркера
        assert releases[0]["data"]["releases"][0]["index"] == 0


def _ticket(owner, idx, gen):
    return _ref(owner, idx, gen)
