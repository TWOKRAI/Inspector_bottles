# -*- coding: utf-8 -*-
"""H7 (Ф7 G.3) + Task 4.4: ProcessIO.write_frames_to_shm — тот же контракт, что FrameShmMiddleware.

Публичный API на каждом процессе с plugins (живых вызовов 0, но контракт держим —
урок G.2 «неиспользуемые пути = контракты»): возвращает SHM-ссылку кадра
``{"owner", "slot", "idx", "gen", "name"}`` (формат ``data["_shm_refs"][key]``) + round-robin
(снят сломанный find_free_index, всегда 0).
"""

from __future__ import annotations

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.io.process_io import ProcessIO
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import MemoryManager
from multiprocess_framework.modules.shared_resources_module.memory.reader import ShmFrameReader


class _FakeProc:
    def __init__(self, mm) -> None:
        self.name = "proc"
        self.memory_manager = mm

    def send_message(self, *a, **k) -> bool:
        return True


def test_write_frames_returns_frame_ref_and_round_robin():
    mm = MemoryManager()
    try:
        mm.create_memory_dict("region", {"slot": (1, (8, 8, 3), "uint8")}, coll=3)
        io = ProcessIO(_FakeProc(mm))
        frame = np.full((8, 8, 3), 5, np.uint8)
        refs = [io.write_frames_to_shm("region", "slot", [frame]) for _ in range(4)]
        assert all(r is not None for r in refs)
        assert all(set(r) == {"owner", "slot", "idx", "gen", "name"} for r in refs), "формат ссылки Task 4.4"
        assert all(r["owner"] == "region" and r["slot"] == "slot" for r in refs)
        assert all(r["gen"] > 0 and r["gen"] % 2 == 0 for r in refs), "gen — ЧЁТНОЕ поколение записи"
        assert [r["idx"] for r in refs] == [0, 1, 2, 0], "round-robin, не find_free_index=0"
    finally:
        mm.close_all()


def test_write_frames_ref_reads_back_by_generation():
    """Ссылка из write_frames_to_shm читается по (name, gen); после перезаписи ячейки — stale (None)."""
    mm = MemoryManager()
    reader = ShmFrameReader()
    try:
        mm.create_memory_dict("r", {"s": (1, (4, 4, 3), "uint8")}, coll=1)
        io = ProcessIO(_FakeProc(mm))
        first = io.write_frames_to_shm("r", "s", [np.full((4, 4, 3), 7, np.uint8)])
        assert (reader.read_ref(first["name"], first["gen"]) == 7).all()
        second = io.write_frames_to_shm("r", "s", [np.full((4, 4, 3), 9, np.uint8)])  # coll=1: та же ячейка
        assert second["gen"] > first["gen"]
        assert reader.read_ref(first["name"], first["gen"]) is None, "старая ссылка на переписанную ячейку"
        assert (reader.read_ref(second["name"], second["gen"]) == 9).all()
    finally:
        reader.close()
        mm.close_all()


def test_write_frames_rejects_not_single_frame():
    io = ProcessIO(_FakeProc(MemoryManager()))
    with pytest.raises(ValueError):
        io.write_frames_to_shm("r", "s", [np.zeros((4, 4, 3), np.uint8)] * 2)


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


def test_write_frames_none_when_write_fails():
    """H7-контракт: слот создан (get_memory_data валиден), но write_images вернул
    None (запись сорвалась) → метод отдаёт None, не мусорный dict."""
    mm = MemoryManager()
    try:
        mm.create_memory_dict("r", {"s": (1, (4, 4, 3), "uint8")}, coll=1)
        mm.write_images = lambda *a, **k: None  # type: ignore[assignment]
        io = ProcessIO(_FakeProc(mm))
        assert io.write_frames_to_shm("r", "s", [np.zeros((4, 4, 3), np.uint8)]) is None
    finally:
        mm.close_all()
