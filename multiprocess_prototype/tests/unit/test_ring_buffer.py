"""Unit-тесты для RingBufferWriter/Reader (AD-6)."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest

from multiprocess_prototype.backend.shm.ring_buffer import (
    RingBufferReader,
    RingBufferWriter,
)


@pytest.fixture
def mock_mm():
    """Mock MemoryManager для unit-тестов без реального SHM."""
    mm = MagicMock()
    mm.write_images = MagicMock(return_value="actual_name")
    # read_images возвращает список из одного кадра
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mm.read_images = MagicMock(return_value=[frame])
    return mm


@pytest.fixture
def writer(mock_mm):
    return RingBufferWriter(mock_mm, owner="camera_0", slot_prefix="camera_0_frame", k=3)


class TestRingBufferWriter:
    def test_write_returns_seq_id_and_slot(self, writer):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        slot, seq = writer.write(frame)
        assert slot == 0
        assert seq == 0

    def test_seq_id_monotonic(self, writer):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        seqs = []
        for _ in range(10):
            _, seq = writer.write(frame)
            seqs.append(seq)
        assert seqs == list(range(10))

    def test_slot_wraps_around(self, writer):
        """Слот индекс wrap-ится по K."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        slots = []
        for _ in range(7):  # K=3, должен wrap 2 раза
            slot, _ = writer.write(frame)
            slots.append(slot)
        assert slots == [0, 1, 2, 0, 1, 2, 0]

    def test_can_write_no_consumers(self, writer):
        """Без consumers — всегда можно писать."""
        assert writer.can_write() is True

    def test_drop_oldest_single_consumer(self, writer):
        """K+1 кадров с 1 consumer → drops_count == 1."""
        writer.register_consumer("proc")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Пишем K+1 = 4 кадра, consumer ничего не читает
        for _ in range(4):
            writer.write(frame)

        # Consumer отстал — drops должны быть
        drops = writer.get_consumer_drops("proc")
        assert drops >= 1, f"Expected drops >= 1, got {drops}"

    def test_drop_oldest_fast_and_slow(self, writer):
        """2 consumers: fast читает всё, slow отстаёт."""
        writer.register_consumer("fast")
        writer.register_consumer("slow")
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        # Пишем 10 кадров
        results = []
        for _ in range(10):
            slot, seq = writer.write(frame)
            results.append((slot, seq))
            # fast consumer "читает" сразу (обновляем last_read_seq)
            writer._consumers["fast"].last_read_seq = seq

        # slow не читал ничего — должны быть drops
        fast_drops = writer.get_consumer_drops("fast")
        slow_drops = writer.get_consumer_drops("slow")
        assert fast_drops == 0, f"Fast should have 0 drops, got {fast_drops}"
        assert slow_drops > 0, f"Slow should have drops, got {slow_drops}"

    def test_register_unregister_consumer(self, writer):
        writer.register_consumer("test")
        assert "test" in writer.get_total_drops()
        writer.unregister_consumer("test")
        assert "test" not in writer.get_total_drops()


class TestRingBufferReader:
    def test_read_returns_frame(self, mock_mm):
        reader = RingBufferReader(
            memory_manager=mock_mm,
            owner="camera_0",
            slot_prefix="camera_0_frame",
            k=3,
            consumer_id="proc",
        )
        frame = reader.read(slot_index=0, seq_id=0)
        assert frame is not None
        assert isinstance(frame, np.ndarray)

    def test_detects_drops(self, mock_mm):
        reader = RingBufferReader(
            memory_manager=mock_mm,
            owner="camera_0",
            slot_prefix="camera_0_frame",
            k=3,
            consumer_id="proc",
        )
        # Читаем seq_id=0, потом seq_id=5 (пропуск 1,2,3,4)
        reader.read(slot_index=0, seq_id=0)
        reader.read(slot_index=2, seq_id=5)
        assert reader.drops_count == 4

    def test_seq_id_tracked(self, mock_mm):
        reader = RingBufferReader(
            memory_manager=mock_mm,
            owner="camera_0",
            slot_prefix="camera_0_frame",
            k=3,
            consumer_id="proc",
        )
        reader.read(slot_index=0, seq_id=0)
        assert reader.last_read_seq == 0
        reader.read(slot_index=1, seq_id=1)
        assert reader.last_read_seq == 1
