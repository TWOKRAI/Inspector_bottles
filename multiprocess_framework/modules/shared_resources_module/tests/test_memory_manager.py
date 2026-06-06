"""
Тесты для memory/memory_manager.py.

Используем только локальный режим (без PSR) для изолированных unit-тестов.
Тесты с PSR — в test_shared_resources_manager.py (интеграционные).

На macOS SharedMemory может работать иначе — тесты помечены skip.
"""

import platform
import numpy as np
import pytest

from ..memory.core import MemoryManager

# SharedMemory на macOS (особенно M1/M2) может возвращать None — см. PROBLEMS.md
pytestmark = pytest.mark.skipif(
    platform.system() == "Darwin",
    reason="MemoryManager SharedMemory tests unreliable on macOS",
)


SHAPE = (10, 10, 3)
DTYPE = np.uint8
MEMORY_CONFIG = {
    "test_mem": (2, SHAPE, DTYPE),
}


@pytest.fixture
def mm():
    manager = MemoryManager()
    manager.initialize()
    yield manager
    manager.shutdown()


def make_image(val: int = 128) -> np.ndarray:
    return np.full(SHAPE, val, dtype=DTYPE)


class TestMemoryManagerCreate:
    def test_create_memory_dict_local(self, mm):
        result = mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        assert result is True

    def test_create_sets_handles(self, mm):
        """В standalone-режиме (без PSR) handles идут в _local_handles[process_name]."""
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        handles = mm._local_handles.get("p1", {}).get("test_mem")
        assert handles is not None
        assert len(handles) == 2

    def test_find_free_index(self, mm):
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        idx = mm.find_free_index("p1", "test_mem")
        assert idx == 0


class TestMemoryManagerWriteRead:
    def test_write_and_read_images(self, mm):
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        images = [make_image(100), make_image(200)]
        shm_name = mm.write_images("p1", "test_mem", images, index=0)
        assert shm_name is not None

        read_back = mm.read_images("p1", "test_mem", index=0)
        assert read_back is not None
        assert len(read_back) == 2
        assert np.array_equal(read_back[0], images[0])
        assert np.array_equal(read_back[1], images[1])

    def test_read_empty_returns_empty_list(self, mm):
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        result = mm.read_images("p1", "test_mem", index=0)
        assert result == []

    def test_write_wrong_dtype_raises(self, mm):
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        wrong_img = np.zeros(SHAPE, dtype=np.float32)
        result = mm.write_images("p1", "test_mem", [wrong_img], index=0)
        assert result is None

    def test_write_invalid_index_returns_none(self, mm):
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        result = mm.write_images("p1", "test_mem", [make_image()], index=99)
        assert result is None


class TestMemoryManagerRelease:
    def test_release_memory(self, mm):
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        mm.write_images("p1", "test_mem", [make_image()], index=0)
        mm.release_memory("p1", "test_mem", index=0)
        # После release индекс должен быть свободен
        idx = mm.find_free_index("p1", "test_mem")
        assert idx == 0

    def test_close_memory(self, mm):
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        mm.close_memory("p1", "test_mem")
        assert mm._local_handles.get("p1", {}).get("test_mem") is None
        assert mm._local_meta.get("p1", {}).get("test_mem") is None


class TestMemoryManagerUnifiedPath:
    def test_get_memory_data_has_unified_structure(self, mm):
        """get_memory_data() возвращает одинаковую структуру в standalone и PSR режимах."""
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        data = mm.get_memory_data("p1", "test_mem")
        assert data is not None
        assert "handles" in data
        assert "params" in data
        assert "index_usage" in data
        assert "coll" in data
        assert "names" in data
        assert data["handles"] is not None
        assert len(data["handles"]) == 2
        assert "test_mem" in data["params"]
        assert "test_mem" in data["coll"]
        assert data["coll"]["test_mem"] == 2

    def test_no_legacy_local_memories(self, mm):
        """_local_memories больше не существует — единый путь через _local_handles."""
        assert not hasattr(mm, "_local_memories"), "_local_memories должен быть удалён, используй _local_handles"

    def test_standalone_meta_is_consistent(self, mm):
        """Метаданные в standalone-режиме согласованы с handles."""
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        meta = mm._local_meta.get("p1", {}).get("test_mem")
        assert meta is not None
        assert meta.coll == 2
        assert len(meta.index_usage) == 2
        assert meta.params == MEMORY_CONFIG["test_mem"]

    def test_write_read_standalone_consistent(self, mm):
        """write/read работают через единый путь без PSR."""
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        img = np.full(SHAPE, 77, dtype=DTYPE)
        shm_name = mm.write_images("p1", "test_mem", [img], index=0)
        assert shm_name is not None
        result = mm.read_images("p1", "test_mem", index=0)
        assert result is not None
        assert np.array_equal(result[0], img)


class TestMemoryManagerReleaseProcess:
    """release_process_memory — полный teardown SHM процесса при hot-swap."""

    MULTI_CONFIG = {
        "mem_a": (2, SHAPE, DTYPE),
        "mem_b": (1, SHAPE, DTYPE),
    }

    def test_release_closes_all_blocks(self, mm):
        """Все блоки процесса закрыты, процесс исчез из _local_handles/_local_meta."""
        mm.create_memory_dict("p1", self.MULTI_CONFIG, coll=2)
        assert mm._local_handles.get("p1") is not None
        assert len(mm._local_handles["p1"]) == 2

        mm.release_process_memory("p1")

        assert "p1" not in mm._local_handles
        assert "p1" not in mm._local_meta

    def test_release_unknown_process_is_noop(self, mm):
        """release несуществующего процесса не падает."""
        mm.release_process_memory("ghost")  # не должно бросить

    def test_switch_a_b_a_no_leak(self, mm):
        """switch A→B→A: число процессов с handles не растёт (нет утечки сегментов).

        Регресс-гард к hot-swap: после release старого процесса его имя/handles
        свободны, новый процесс создаёт свежие ячейки без накопления.
        """
        for _ in range(3):
            mm.create_memory_dict("proc_a", MEMORY_CONFIG, coll=2)
            assert len(mm._local_handles) == 1  # только proc_a
            mm.release_process_memory("proc_a")
            assert len(mm._local_handles) == 0  # очищено

            mm.create_memory_dict("proc_b", MEMORY_CONFIG, coll=2)
            assert len(mm._local_handles) == 1  # только proc_b
            mm.release_process_memory("proc_b")
            assert len(mm._local_handles) == 0

    def test_release_then_recreate_same_name(self, mm):
        """После release имя свободно — пересоздание того же процесса работает."""
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        mm.release_process_memory("p1")

        ok = mm.create_memory_dict("p1", MEMORY_CONFIG, coll=2)
        assert ok is True
        # Новые ячейки созданы и доступны для записи
        shm_name = mm.write_images("p1", "test_mem", [make_image(55)], index=0)
        assert shm_name is not None


class TestMemoryManagerSafeClose:
    def test_safe_close_none_is_noop(self, mm):
        mm._safe_close_shm(None)  # не должно упасть

    def test_shutdown_closes_all(self, mm):
        mm.create_memory_dict("p1", MEMORY_CONFIG, coll=1)
        mm.shutdown()
        assert len(mm._local_handles) == 0
        assert len(mm._local_meta) == 0
