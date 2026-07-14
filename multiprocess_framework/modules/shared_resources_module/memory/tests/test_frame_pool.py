# -*- coding: utf-8 -*-
"""Ф7 H-задача (консолидация памяти): contract-тесты фасада `FramePool`/`LoanLedger`.

Проверяют семантику владения слотом в ИЗОЛЯЦИИ от транспорта (перенос из
`router_module` за фасад модуля памяти БЕЗ смены поведения): acquire/commit/release/
reclaim/reset/snapshot_stats + guard'ы release (refcount==0 / stale generation / dup
reader). Интеграция транспорта с пулом — `router_module/tests/test_g5d_loan.py`.
"""

from __future__ import annotations

from multiprocess_framework.modules.shared_resources_module.memory.pool import (
    FramePool,
    LoanLedger,
)


class TestProtocolConformance:
    def test_loan_ledger_is_frame_pool(self):
        """LoanLedger удовлетворяет Protocol FramePool (runtime_checkable)."""
        assert isinstance(LoanLedger(3), FramePool)

    def test_depth_clamped_min_one(self):
        assert LoanLedger(0).depth == 1
        assert LoanLedger(5).depth == 5


class TestAcquireCommit:
    def test_rotates_and_exhausts(self):
        """acquire ротирует курсор; когда все заняты → None + счётчик исчерпания."""
        p = LoanLedger(3)
        assert p.acquire() == 0
        assert p.acquire() == 1
        assert p.acquire() == 2
        # курсор обернулся, слоты ещё свободны (commit не звали) → снова 0.
        assert p.acquire() == 0
        assert p.snapshot_stats()["loan_exhausted"] == 0
        # Занять все через commit → исчерпание.
        for i in range(3):
            p.commit(i, 1)
        assert p.acquire() is None
        assert p.snapshot_stats()["loan_exhausted"] == 1

    def test_commit_sets_refcount_fanout(self):
        """commit ставит refcount = num_consumers (fan-out)."""
        p = LoanLedger(2)
        idx = p.acquire()
        p.commit(idx, 2)
        # слот занят двумя → второй acquire уходит на другой слот, не на этот.
        assert p.acquire() != idx

    def test_commit_clamps_min_one(self):
        p = LoanLedger(1)
        p.commit(0, 0)  # <1 → 1 (иначе слот сразу «свободен» = логическая дыра)
        assert p.acquire() is None  # занят


class TestRelease:
    def _gen0(self, _idx):
        return 0  # стабильное поколение (seqlock-заглушка)

    def test_release_reopens_slot(self):
        p = LoanLedger(2, gen_reader=self._gen0)
        i0 = p.acquire()
        p.commit(i0, 1)
        p.acquire()  # i1
        p.commit(1, 1)
        assert p.acquire() is None  # исчерпан
        freed = p.release([{"index": i0, "generation": 0, "reader": "c0"}])
        assert freed == 1
        assert p.snapshot_stats()["slots_released"] == 1
        assert p.acquire() == i0  # снова свободен

    def test_dedup_and_fanout(self):
        p = LoanLedger(2, gen_reader=self._gen0)
        idx = p.acquire()
        p.commit(idx, 2)
        t0 = {"index": idx, "generation": 0, "reader": "c0"}
        assert p.release([t0]) == 1
        assert p.release([t0]) == 0  # дубликат c0 → игнор
        assert p.release([{"index": idx, "generation": 0, "reader": "c1"}]) == 1
        # оба отпустили → слот свободен (refcount вернулся в 0).
        assert p._refcount[idx] == 0

    def test_stale_generation_ignored(self):
        p = LoanLedger(2, gen_reader=self._gen0)
        idx = p.acquire()
        p.commit(idx, 1)
        # gen тикета (99) ≠ текущему (0) → release прошлого займа → пропуск.
        assert p.release([{"index": idx, "generation": 99, "reader": "c0"}]) == 0

    def test_release_on_free_slot_skipped(self):
        p = LoanLedger(2, gen_reader=self._gen0)
        # refcount==0 (никто не занимал) → пропуск.
        assert p.release([{"index": 0, "generation": 0, "reader": "c0"}]) == 0

    def test_out_of_range_and_malformed_ticket(self):
        p = LoanLedger(2, gen_reader=self._gen0)
        assert p.release([{"index": 9, "generation": 0, "reader": "c0"}]) == 0
        assert p.release([{"index": "x", "generation": 0, "reader": "c0"}]) == 0
        assert p.release([]) == 0

    def test_no_gen_reader_guard_is_noop(self):
        """Без gen_reader (дефолт -1) и тикет с -1 → guard пропускает (как без seqlock)."""
        p = LoanLedger(1)  # gen_reader → -1
        idx = p.acquire()
        p.commit(idx, 1)
        assert p.release([{"index": idx, "generation": -1, "reader": "c0"}]) == 1


class TestReclaim:
    def _gen0(self, _idx):
        return 0

    def test_reclaim_frees_dead_holder(self):
        p = LoanLedger(2)
        p.commit(p.acquire(), 1)
        p.commit(p.acquire(), 1)
        assert p.acquire() is None  # исчерпан
        assert p.reclaim("c0") == 2
        assert p.snapshot_stats()["slots_reclaimed"] == 2
        assert p.acquire() is not None  # восстановлен

    def test_reclaim_idempotent(self):
        p = LoanLedger(2)
        p.commit(p.acquire(), 1)
        assert p.reclaim("c0") == 1
        assert p.reclaim("c0") == 0

    def test_reclaim_partial_fanout(self):
        p = LoanLedger(1)
        p.commit(p.acquire(), 2)
        assert p.reclaim("c0") == 1  # c0 умер → -1
        assert p.reclaim("c1") == 1  # c1 умер → освобождён
        assert p.acquire() == 0

    def test_reclaim_skips_already_released(self):
        p = LoanLedger(1, gen_reader=self._gen0)
        idx = p.acquire()
        p.commit(idx, 2)
        p.release([{"index": idx, "generation": 0, "reader": "c0"}])  # c0 отпустил
        assert p.reclaim("c0") == 0  # уже в released → пропуск
        assert p.reclaim("c1") == 1  # c1 держал → освобождён

    def test_reclaim_empty_reader(self):
        assert LoanLedger(2).reclaim("") == 0


class TestReset:
    def test_reset_frees_all_keeps_counters(self):
        p = LoanLedger(2)
        p.commit(p.acquire(), 1)
        p.commit(p.acquire(), 1)
        p.acquire()  # None → exhausted=1
        assert p.snapshot_stats()["loan_exhausted"] == 1
        p.reset()
        # всё свободно, курсор с начала.
        assert p.acquire() == 0
        # счётчики наблюдаемости НЕ обнулены (realloc не теряет историю).
        assert p.snapshot_stats()["loan_exhausted"] == 1
