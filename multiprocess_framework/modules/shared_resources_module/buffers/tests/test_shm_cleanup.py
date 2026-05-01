"""Unit-тесты для ShmRegistry и cleanup_stale_shm."""

from __future__ import annotations

import sys
import threading
from multiprocessing import shared_memory

import pytest

from multiprocess_framework.modules.shared_resources_module.buffers import (
    ShmRegistry,
    cleanup_stale_shm,
)


class TestShmRegistry:
    def test_register_and_all_names(self, tmp_path):
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        reg.register("test_shm_a")
        reg.register("test_shm_b")
        names = reg.all_names()
        assert "test_shm_a" in names
        assert "test_shm_b" in names

    def test_register_deduplicates(self, tmp_path):
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        reg.register("shm_x")
        reg.register("shm_x")
        assert reg.all_names().count("shm_x") == 1

    def test_unregister_removes_name(self, tmp_path):
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        reg.register("shm_y")
        reg.unregister("shm_y")
        assert "shm_y" not in reg.all_names()

    def test_unregister_nonexistent_is_safe(self, tmp_path):
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        reg.unregister("nonexistent")

    def test_clear_removes_file(self, tmp_path):
        reg_path = tmp_path / ".shm_registry.json"
        reg = ShmRegistry(path=reg_path)
        reg.register("shm_z")
        assert reg_path.exists()
        reg.clear()
        assert not reg_path.exists()

    def test_all_names_when_file_missing(self, tmp_path):
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        assert reg.all_names() == []

    def test_all_names_with_corrupted_file(self, tmp_path):
        reg_path = tmp_path / ".shm_registry.json"
        reg_path.write_text("not valid json", encoding="utf-8")
        reg = ShmRegistry(path=reg_path)
        assert reg.all_names() == []

    def test_registry_persists_to_disk(self, tmp_path):
        reg_path = tmp_path / ".shm_registry.json"
        reg1 = ShmRegistry(path=reg_path)
        reg1.register("persistent_shm")
        reg2 = ShmRegistry(path=reg_path)
        assert "persistent_shm" in reg2.all_names()

    def test_concurrent_register_no_lost_entries(self, tmp_path):
        """Конкурентный register() из N потоков не должен терять записи."""
        reg_path = tmp_path / ".shm_registry.json"
        reg = ShmRegistry(path=reg_path)
        n = 20
        names = [f"shm_thread_{i}" for i in range(n)]

        threads = [threading.Thread(target=reg.register, args=(name,)) for name in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        result = reg.all_names()
        assert len(result) == n
        for name in names:
            assert name in result

    def test_concurrent_register_deduplicates(self, tmp_path):
        """Конкурентный register() одного имени не создаёт дубликатов."""
        reg_path = tmp_path / ".shm_registry.json"
        reg = ShmRegistry(path=reg_path)

        threads = [threading.Thread(target=reg.register, args=("shared_name",)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert reg.all_names().count("shared_name") == 1


class TestCleanupStaleShmEmpty:
    def test_empty_known_names_returns_empty(self):
        assert cleanup_stale_shm(known_names=[]) == []

    def test_none_known_names_returns_empty(self):
        assert cleanup_stale_shm(known_names=None) == []

    def test_nonexistent_names_returns_empty(self):
        result = cleanup_stale_shm(known_names=["nonexistent_shm_abc123", "another_fake_shm"])
        assert result == []


class TestCleanupStaleShmReal:
    """Тесты с реальным SharedMemory."""

    def test_cleanup_removes_existing_shm_linux(self):
        if not sys.platform.startswith("linux"):
            pytest.skip("Linux-only тест")

        base_name = "test_fw_cleanup_slot"
        shm_name = f"{base_name}_0"

        shm = shared_memory.SharedMemory(name=shm_name, create=True, size=1024)
        shm.close()

        try:
            cleaned = cleanup_stale_shm(known_names=[base_name])
            assert shm_name in cleaned
            with pytest.raises((FileNotFoundError, Exception)):
                probe = shared_memory.SharedMemory(name=shm_name, create=False)
                probe.close()
        finally:
            try:
                leftover = shared_memory.SharedMemory(name=shm_name, create=False)
                leftover.close()
                leftover.unlink()
            except Exception:
                pass

    def test_cleanup_multiple_slots(self):
        if not sys.platform.startswith("linux"):
            pytest.skip("Linux-only тест")

        base_name = "test_fw_multislot"
        coll = 3
        for i in range(coll):
            shm = shared_memory.SharedMemory(name=f"{base_name}_{i}", create=True, size=512)
            shm.close()

        try:
            cleaned = cleanup_stale_shm(known_names=[base_name])
            assert len(cleaned) == coll
            for i in range(coll):
                assert f"{base_name}_{i}" in cleaned
        finally:
            for i in range(coll):
                try:
                    leftover = shared_memory.SharedMemory(name=f"{base_name}_{i}", create=False)
                    leftover.close()
                    leftover.unlink()
                except Exception:
                    pass
