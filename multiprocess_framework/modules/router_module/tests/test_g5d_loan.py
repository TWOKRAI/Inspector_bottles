# -*- coding: utf-8 -*-
"""Ф7 G.5.d-1 — owner-side free-list + loan-on-write + громкое исчерпание (В3).

loan-протокол: запись берёт СВОБОДНЫЙ слот (refcount==0) вместо слепого round-robin,
ставит refcount=num_consumers. Свободных нет (читатели отстали, release ещё нет в d-1)
→ громкий drop-на-источнике (frame_loan_exhausted; send-middleware → None). Дефолт off
= слепой round-robin бит-в-бит. release (замыкание кольца) — G.5.d-2.
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)


def _frame(val: int = 1, h: int = 32, w: int = 32) -> np.ndarray:
    return np.full((h, w, 3), val, dtype=np.uint8)


class TestLoanOff:
    def test_blind_round_robin_bit_exact(self, monkeypatch):
        """Флаг off → прежний слепой round-robin, без исчерпания."""
        monkeypatch.delenv("FW_SHM_LOAN_PROTOCOL", raising=False)
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="output_frames", coll=3)
        assert mw._loan_protocol is False
        try:
            indices = [mw.strip_and_write({"frame": _frame(i)}).get("shm_index") for i in range(7)]
            assert indices == [0, 1, 2, 0, 1, 2, 0]  # слепой цикл
            assert mw.frame_loan_exhausted == 0
        finally:
            mw.release_owned_memory()


class TestLoanOn:
    def test_takes_free_slots_then_exhausts(self, monkeypatch):
        """3 кадра занимают 3 слота (release нет) → 4-й: free-list исчерпан → drop."""
        monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="output_frames", coll=3)
        assert mw._loan_protocol is True
        try:
            for i in range(3):
                item = mw.strip_and_write({"frame": _frame(i)})
                assert "frame" not in item  # записан в SHM (loan занял слот)
            assert mw._slot_refcount == [1, 1, 1]  # все слоты выданы
            assert mw.frame_loan_exhausted == 0

            # 4-й кадр: свободных слотов нет → drop-на-источнике (кадр остался в item).
            item = mw.strip_and_write({"frame": _frame(9)})
            assert item.get("frame") is not None  # НЕ записан
            assert mw._last_loan_exhausted is True
            assert mw.frame_loan_exhausted == 1
        finally:
            mw.release_owned_memory()

    def test_refcount_equals_num_consumers(self, monkeypatch):
        """loan ставит refcount = num_consumers (fan-out)."""
        monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="s", coll=3, num_consumers=2)
        try:
            mw.strip_and_write({"frame": _frame(1)})
            assert mw._slot_refcount[0] == 2
        finally:
            mw.release_owned_memory()

    def test_send_middleware_drops_on_exhaustion(self, monkeypatch):
        """strip_data_frame_on_send при исчерпании → None (router дропает send)."""
        monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="s", coll=2)
        try:
            for i in range(2):
                r = mw.strip_data_frame_on_send({"type": "data", "data": {"frame": _frame(i)}})
                assert r is not None  # записан, отправка идёт
            # 3-й: исчерпание → None = drop send.
            r = mw.strip_data_frame_on_send({"type": "data", "data": {"frame": _frame(9)}})
            assert r is None
            assert mw.frame_loan_exhausted == 1
        finally:
            mw.release_owned_memory()

    def test_realloc_resets_free_list(self, monkeypatch):
        """Рост кадра → realloc → free-list сброшен (старые займы void, сегменты ушли)."""
        monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="s", coll=3)
        try:
            mw.strip_and_write({"frame": _frame(1, 16, 16)})
            assert mw._slot_refcount == [1, 0, 0]
            # Больший кадр → realloc → refcount/cursor сброшены, затем этот write занял slot 0.
            mw.strip_and_write({"frame": _frame(2, 32, 32)})
            assert mw._slot_refcount == [1, 0, 0]
            assert mw._loan_cursor == 1
        finally:
            mw.release_owned_memory()


class TestReleaseSlots:
    """G.5.d-2: owner-side release декрементит refcount (generation-guard + dedup)."""

    def _mw(self, monkeypatch, coll=2, num_consumers=1):
        monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
        monkeypatch.setenv("FW_SHM_SEQLOCK", "1")  # generation-guard требует seqlock
        return FrameShmMiddleware(
            MemoryManager(), owner="cam", slot="output_frames", coll=coll, num_consumers=num_consumers
        )

    def test_release_reopens_free_list(self, monkeypatch):
        """loan все слоты → исчерпание; release одного → снова доступен."""
        mw = self._mw(monkeypatch, coll=2)
        try:
            i0 = mw.strip_and_write({"frame": _frame(0)})["shm_index"]
            mw.strip_and_write({"frame": _frame(1)})  # i1
            gen0 = mw._read_own_slot_generation(i0)
            # исчерпан → drop-на-источнике
            assert mw.strip_and_write({"frame": _frame(2)}).get("frame") is not None
            assert mw.frame_loan_exhausted == 1
            # release i0 → свободен → loan снова проходит на i0.
            mw.release_slots([{"index": i0, "generation": gen0, "reader": "c0"}])
            assert mw._slot_refcount[i0] == 0
            assert mw.frame_slots_released == 1
            out = mw.strip_and_write({"frame": _frame(3)})
            assert "frame" not in out and out["shm_index"] == i0
        finally:
            mw.release_owned_memory()

    def test_dedup_and_num_consumers(self, monkeypatch):
        """num_consumers=2: слот свободен только когда ОБА читателя отпустили; дубль игнор."""
        mw = self._mw(monkeypatch, coll=2, num_consumers=2)
        try:
            item = mw.strip_and_write({"frame": _frame(1)})
            idx = item["shm_index"]
            gen = mw._read_own_slot_generation(idx)
            assert mw._slot_refcount[idx] == 2
            t0 = {"index": idx, "generation": gen, "reader": "c0"}
            mw.release_slots([t0])
            assert mw._slot_refcount[idx] == 1
            mw.release_slots([t0])  # дубликат c0 → игнор
            assert mw._slot_refcount[idx] == 1
            mw.release_slots([{"index": idx, "generation": gen, "reader": "c1"}])
            assert mw._slot_refcount[idx] == 0  # оба отпустили → свободен
        finally:
            mw.release_owned_memory()

    def test_stale_generation_ignored(self, monkeypatch):
        """release с чужим поколением (прошлый займ) → игнор."""
        mw = self._mw(monkeypatch, coll=2)
        try:
            item = mw.strip_and_write({"frame": _frame(1)})
            idx = item["shm_index"]
            gen = mw._read_own_slot_generation(idx)
            mw.release_slots([{"index": idx, "generation": gen + 100, "reader": "c0"}])
            assert mw._slot_refcount[idx] == 1  # stale gen → не декрементнут
        finally:
            mw.release_owned_memory()

    def test_noop_without_flag(self, monkeypatch):
        """Без loan-протокола release_slots — no-op."""
        monkeypatch.delenv("FW_SHM_LOAN_PROTOCOL", raising=False)
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="s", coll=2)
        mw.release_slots([{"index": 0, "generation": 0, "reader": "c0"}])
        assert mw.frame_slots_released == 0


def _loan_mw(monkeypatch, coll=2, num_consumers=1):
    monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
    monkeypatch.setenv("FW_SHM_SEQLOCK", "1")
    return FrameShmMiddleware(
        MemoryManager(), owner="cam", slot="output_frames", coll=coll, num_consumers=num_consumers
    )


class TestReclaimOnDeath:
    """G.5.e: reclaim займов мёртвого читателя (kill-9 без release) — симуляция смерти
    (держатель занял слоты и НЕ отпустил). При fan-out мёртвый держал все занятые слоты."""

    def test_reclaim_frees_dead_holder_and_recovers(self, monkeypatch):
        """Держатель занял все слоты, «умер» (не отпустил) → исчерпание; reclaim → free."""
        mw = _loan_mw(monkeypatch, coll=2, num_consumers=1)
        try:
            mw.strip_and_write({"frame": _frame(0)})
            mw.strip_and_write({"frame": _frame(1)})
            assert mw.strip_and_write({"frame": _frame(2)}).get("frame") is not None  # исчерпан
            # Мёртвый читатель c0 держал оба слота (не отпустил) → reclaim освобождает.
            assert mw.reclaim_reader("c0") == 2
            assert mw._slot_refcount == [0, 0]
            assert mw.frame_slots_reclaimed == 2
            # free-list восстановлен → loan снова проходит.
            assert "frame" not in mw.strip_and_write({"frame": _frame(3)})
        finally:
            mw.release_owned_memory()

    def test_reclaim_idempotent(self, monkeypatch):
        """Повторный reclaim после освобождения → 0 (не уходит в минус)."""
        mw = _loan_mw(monkeypatch, coll=2, num_consumers=1)
        try:
            mw.strip_and_write({"frame": _frame(0)})  # занят slot0
            assert mw.reclaim_reader("c0") == 1
            assert mw.reclaim_reader("c0") == 0
        finally:
            mw.release_owned_memory()

    def test_reclaim_multi_consumer_partial(self, monkeypatch):
        """num_consumers=2: смерть c0 не освобождает слот, пока жив c1."""
        mw = _loan_mw(monkeypatch, coll=1, num_consumers=2)
        try:
            mw.strip_and_write({"frame": _frame(0)})
            assert mw._slot_refcount[0] == 2
            assert mw.reclaim_reader("c0") == 1  # c0 умер → -1
            assert mw._slot_refcount[0] == 1  # c1 ещё держит
            assert mw.reclaim_reader("c1") == 1  # c1 умер → освобождён
            assert mw._slot_refcount[0] == 0
        finally:
            mw.release_owned_memory()

    def test_reclaim_skips_already_released(self, monkeypatch):
        """Читатель, успевший отпустить до смерти, не декрементится повторно reclaim'ом."""
        mw = _loan_mw(monkeypatch, coll=1, num_consumers=2)
        try:
            item = mw.strip_and_write({"frame": _frame(0)})
            idx = item["shm_index"]
            gen = mw._read_own_slot_generation(idx)
            mw.release_slots([{"index": idx, "generation": gen, "reader": "c0"}])  # c0 отпустил
            assert mw._slot_refcount[idx] == 1
            assert mw.reclaim_reader("c0") == 0  # c0 уже в released → пропуск
            assert mw._slot_refcount[idx] == 1
            assert mw.reclaim_reader("c1") == 1  # c1 умер держа → освобождён
            assert mw._slot_refcount[idx] == 0
        finally:
            mw.release_owned_memory()

    def test_reclaim_noop_without_flag(self, monkeypatch):
        monkeypatch.delenv("FW_SHM_LOAN_PROTOCOL", raising=False)
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="s", coll=2)
        assert mw.reclaim_reader("c0") == 0
        assert mw.frame_slots_reclaimed == 0


class TestAcquireLoanSlot:
    def test_rotates_and_returns_none_when_full(self, monkeypatch):
        """_acquire_loan_slot: ротация курсора; None когда все заняты."""
        monkeypatch.setenv("FW_SHM_LOAN_PROTOCOL", "1")
        mw = FrameShmMiddleware(MemoryManager(), owner="cam", slot="s", coll=3)
        assert mw._acquire_loan_slot() == 0
        assert mw._acquire_loan_slot() == 1
        assert mw._acquire_loan_slot() == 2
        assert mw._acquire_loan_slot() == 0  # курсор обернулся, слоты ещё «свободны» (refcount 0)
        # Занять все вручную → None.
        mw._slot_refcount = [1, 1, 1]
        assert mw._acquire_loan_slot() is None
