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
