# -*- coding: utf-8 -*-
"""Ф7 H-задача (консолидация памяти): contract-тесты фасада `FramePool`/`LoanLedger`.

Проверяют семантику владения слотом в ИЗОЛЯЦИИ от транспорта (перенос из
`router_module` за фасад модуля памяти БЕЗ смены поведения): acquire/commit/release/
reclaim/reset/snapshot_stats + guard'ы release (refcount==0 / stale generation / dup
reader). Интеграция транспорта с пулом — `router_module/tests/test_g5d_loan.py`.
"""

from __future__ import annotations

import threading

import pytest

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
    def test_reserves_on_acquire_then_exhausts(self):
        """acquire РЕЗЕРВИРУЕТ слот (WRITING) — повторный acquire его НЕ выдаёт.

        Резервирование (а не слепой round-robin, как было до H-ревью) — основа
        single-writer: два acquire не могут получить один слот. Все зарезервированы
        (даже без commit) → исчерпание.
        """
        p = LoanLedger(3)
        assert p.acquire() == 0
        assert p.acquire() == 1
        assert p.acquire() == 2
        # все три WRITING (зарезервированы), commit не звали → исчерпание, НЕ повтор 0.
        assert p.acquire() is None
        assert p.snapshot_stats()["loan_exhausted"] == 1
        # commit публикует — семантика занятости та же (слот остаётся busy).
        p.commit(0, 1)
        assert p.acquire() is None
        assert p.snapshot_stats()["loan_exhausted"] == 2

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

    def test_reset_clears_reservation(self):
        """reset снимает WRITING-резервы (realloc кольца): зарезервированные acquire'ом
        слоты снова свободны (H-ревью: без сброса reserved они утекли бы после realloc)."""
        p = LoanLedger(2)
        p.acquire()  # reserve 0 (без commit)
        p.acquire()  # reserve 1
        assert p.acquire() is None  # оба WRITING → исчерпан
        p.reset()
        assert p.acquire() == 0  # резервы сняты


class TestLoanLifecycle:
    """H-ревью 2026-07-14: loan ОБЯЗАН завершиться commit ЛИБО abort (iceoryx2-контракт)."""

    def test_abort_returns_slot_to_free(self):
        """abort отменяет loan (write не удался) → слот снова свободен (не утёк WRITING)."""
        p = LoanLedger(1)
        idx = p.acquire()
        assert p.acquire() is None  # зарезервирован (WRITING)
        p.abort(idx)
        assert p.acquire() == idx  # вернулся в free

    def test_abort_out_of_range_noop(self):
        p = LoanLedger(1)
        p.abort(9)  # не падает
        p.abort(-1)
        assert p.acquire() == 0

    def test_commit_clears_reservation(self):
        """commit публикует (WRITING→READY) и снимает резерв."""
        p = LoanLedger(2)
        idx = p.acquire()
        assert p._reserved[idx] is True
        p.commit(idx, 1)
        assert p._reserved[idx] is False
        assert p._refcount[idx] == 1

    def test_abort_does_not_touch_committed_slot(self):
        """abort снимает только резерв; на уже опубликованном (READY) слоте refcount цел."""
        p = LoanLedger(2, gen_reader=lambda _i: 0)
        idx = p.acquire()
        p.commit(idx, 1)
        p.abort(idx)  # резерв уже снят commit'ом → refcount не трогается
        assert p._refcount[idx] == 1


class TestSingleWriterGuard:
    """H-ревью 2026-07-14: single-writer enforced кодом, а не соглашением."""

    def test_same_thread_many_acquire_ok(self):
        """Тот же поток-писатель зовёт acquire многократно — без ошибки."""
        p = LoanLedger(3)
        assert p.acquire() == 0
        assert p.acquire() == 1  # тот же поток → ok

    def test_second_writer_thread_raises(self):
        """Второй ИНОЙ поток, зовущий acquire → RuntimeError (write-write не допускается)."""
        p = LoanLedger(3)
        p.acquire()  # связывает поток-писатель (main)
        captured: dict = {}

        def intruder():
            try:
                p.acquire()
            except RuntimeError as exc:
                captured["exc"] = exc

        t = threading.Thread(target=intruder)
        t.start()
        t.join()
        assert isinstance(captured.get("exc"), RuntimeError)

    def test_release_and_reclaim_from_other_thread_ok(self):
        """release/reclaim на другом потоке (message_processor владельца) — легитимны:
        это НЕ второй писатель (guard только на acquire), они трогают READY-слоты."""
        p = LoanLedger(2, gen_reader=lambda _i: 0)
        idx = p.acquire()  # main = писатель
        p.commit(idx, 2)
        out: dict = {}

        def owner_msg_thread():
            try:
                out["freed"] = p.release([{"index": idx, "generation": 0, "reader": "c0"}])
                out["reclaimed"] = p.reclaim("cX")  # cX держал второй займ fan-out
            except Exception as exc:  # noqa: BLE001
                out["exc"] = exc

        t = threading.Thread(target=owner_msg_thread)
        t.start()
        t.join()
        assert "exc" not in out
        assert out["freed"] == 1
        assert out["reclaimed"] == 1

    def test_guard_message_names_both_threads(self):
        """Сообщение RuntimeError содержит оба ident (диагностируемость нарушения)."""
        p = LoanLedger(2)
        p.acquire()
        with pytest.raises(RuntimeError, match="ВТОРОЙ писатель"):
            # эмулируем второй поток простым перебиндом ident-проверки нельзя —
            # зовём из этого же потока после ручного сброса на «чужой» ident.
            p._writer_ident = p._writer_ident + 1 if p._writer_ident else 1
            p.acquire()
