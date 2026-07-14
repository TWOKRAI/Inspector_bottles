# -*- coding: utf-8 -*-
"""H7 (Ф7 G.3): ProcessIO.write_frames_to_shm — тот же контракт, что FrameShmMiddleware.

Публичный API на каждом процессе с plugins (живых вызовов 0, но контракт держим —
урок G.2 «неиспользуемые пути = контракты»): shm_seqlock из АВТОРИТЕТНОГО
get_memory_data + round-robin (снят сломанный find_free_index, всегда 0).
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.process_module.io.process_io import ProcessIO
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager


class _FakeProc:
    def __init__(self, mm) -> None:
        self.name = "proc"
        self.memory_manager = mm

    def send_message(self, *a, **k) -> bool:
        return True


def test_write_frames_stamps_seqlock_and_round_robin():
    mm = MemoryManager(seqlock_frames=True)
    try:
        mm.create_memory_dict("region", {"slot": (1, (8, 8, 3), "uint8")}, coll=3)
        io = ProcessIO(_FakeProc(mm))
        frame = np.full((8, 8, 3), 5, np.uint8)
        refs = [io.write_frames_to_shm("region", "slot", [frame]) for _ in range(4)]
        assert all(r is not None for r in refs)
        assert all(r["shm_seqlock"] is True for r in refs), "H7: seqlock обязан быть в контракте"
        assert [r["shm_index"] for r in refs] == [0, 1, 2, 0], "round-robin, не find_free_index=0"
    finally:
        mm.close_all()


def test_write_frames_seqlock_false_when_slot_plain():
    mm = MemoryManager()  # seqlock off
    try:
        mm.create_memory_dict("r", {"s": (1, (4, 4, 3), "uint8")}, coll=1)
        io = ProcessIO(_FakeProc(mm))
        ref = io.write_frames_to_shm("r", "s", [np.zeros((4, 4, 3), np.uint8)])
        assert ref is not None and ref["shm_seqlock"] is False
    finally:
        mm.close_all()


def test_write_frames_none_without_mm():
    class _NoMM:
        name = "p"
        memory_manager = None

        def send_message(self, *a, **k) -> bool:
            return True

    io = ProcessIO(_NoMM())
    assert io.write_frames_to_shm("r", "s", [np.zeros((4, 4, 3), np.uint8)]) is None


def test_write_frames_none_when_slot_not_created():
    mm = MemoryManager()
    try:
        io = ProcessIO(_FakeProc(mm))
        # Слот не создан → get_memory_data None → контракт возвращает None (не падает).
        assert io.write_frames_to_shm("r", "missing", [np.zeros((4, 4, 3), np.uint8)]) is None
    finally:
        mm.close_all()
