"""Unit-тесты для backend/shm/cleanup.py и backend/shm/registry.py.

Тесты работают без реального запуска приложения.
ShmRegistry — проверяется через временный файл.
cleanup_stale_shm — проверяется через реальный SharedMemory (доступен без root).
"""

from __future__ import annotations

import sys
from multiprocessing import shared_memory
from pathlib import Path

import pytest

from multiprocess_prototype_v3.backend.shm.cleanup import cleanup_stale_shm
from multiprocess_prototype_v3.backend.shm.registry import ShmRegistry

# ===========================================================================
# Тесты ShmRegistry
# ===========================================================================


class TestShmRegistry:
    def test_register_and_all_names(self, tmp_path):
        """register() добавляет имя, all_names() его возвращает."""
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        reg.register("test_shm_a")
        reg.register("test_shm_b")
        names = reg.all_names()
        assert "test_shm_a" in names
        assert "test_shm_b" in names

    def test_register_deduplicates(self, tmp_path):
        """Повторный register() не добавляет дубликаты."""
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        reg.register("shm_x")
        reg.register("shm_x")
        assert reg.all_names().count("shm_x") == 1

    def test_unregister_removes_name(self, tmp_path):
        """unregister() убирает имя из реестра."""
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        reg.register("shm_y")
        reg.unregister("shm_y")
        assert "shm_y" not in reg.all_names()

    def test_unregister_nonexistent_is_safe(self, tmp_path):
        """unregister() не падает если имя не зарегистрировано."""
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        reg.unregister("nonexistent")  # не должно бросать исключение

    def test_clear_removes_file(self, tmp_path):
        """clear() удаляет файл реестра."""
        reg_path = tmp_path / ".shm_registry.json"
        reg = ShmRegistry(path=reg_path)
        reg.register("shm_z")
        assert reg_path.exists()
        reg.clear()
        assert not reg_path.exists()

    def test_all_names_when_file_missing(self, tmp_path):
        """all_names() возвращает [] если файл реестра не существует."""
        reg = ShmRegistry(path=tmp_path / ".shm_registry.json")
        assert reg.all_names() == []

    def test_all_names_with_corrupted_file(self, tmp_path):
        """all_names() возвращает [] если файл реестра повреждён."""
        reg_path = tmp_path / ".shm_registry.json"
        reg_path.write_text("not valid json", encoding="utf-8")
        reg = ShmRegistry(path=reg_path)
        assert reg.all_names() == []

    def test_registry_persists_to_disk(self, tmp_path):
        """Данные реестра сохраняются на диск и читаются новым экземпляром."""
        reg_path = tmp_path / ".shm_registry.json"
        reg1 = ShmRegistry(path=reg_path)
        reg1.register("persistent_shm")

        # Новый экземпляр читает тот же файл
        reg2 = ShmRegistry(path=reg_path)
        assert "persistent_shm" in reg2.all_names()


# ===========================================================================
# Тесты cleanup_stale_shm
# ===========================================================================


class TestCleanupStaleShmEmpty:
    def test_empty_known_names_returns_empty(self):
        """cleanup с пустым списком known_names возвращает [] без ошибок."""
        result = cleanup_stale_shm(known_names=[])
        assert result == []

    def test_none_known_names_returns_empty(self):
        """cleanup с known_names=None возвращает [] без ошибок."""
        result = cleanup_stale_shm(known_names=None)
        assert result == []

    def test_nonexistent_names_returns_empty(self):
        """cleanup несуществующих SHM возвращает [] и не бросает исключений."""
        result = cleanup_stale_shm(known_names=["nonexistent_shm_abc123", "another_fake_shm"])
        assert result == []


class TestCleanupStaleShmReal:
    """Тесты с реальным SharedMemory (требует права на создание SHM)."""

    def test_cleanup_removes_existing_shm_linux(self):
        """На Linux: создать SHM → cleanup по базовому имени → сегмент удалён."""
        if not sys.platform.startswith("linux"):
            pytest.skip("Linux-only тест")

        base_name = "test_inspector_cleanup_slot"
        shm_name = f"{base_name}_0"

        # Создаём SHM сегмент вручную
        shm = shared_memory.SharedMemory(name=shm_name, create=True, size=1024)
        shm.close()

        try:
            # cleanup должен найти и удалить сегмент
            cleaned = cleanup_stale_shm(known_names=[base_name])
            assert shm_name in cleaned, f"Ожидали '{shm_name}' в cleaned, получили: {cleaned}"

            # Повторная попытка открыть — должна завершиться ошибкой (сегмент удалён)
            with pytest.raises((FileNotFoundError, Exception)):
                probe = shared_memory.SharedMemory(name=shm_name, create=False)
                probe.close()
        finally:
            # Страховочный cleanup если тест упал до удаления
            try:
                leftover = shared_memory.SharedMemory(name=shm_name, create=False)
                leftover.close()
                leftover.unlink()
            except Exception:
                pass

    def test_cleanup_no_error_if_shm_already_gone(self):
        """cleanup не бросает исключений если SHM уже не существует."""
        # Имя которого заведомо нет
        result = cleanup_stale_shm(known_names=["inspector_totally_fake_xyz987"])
        assert result == []

    def test_cleanup_multiple_slots(self):
        """На Linux: cleanup обрабатывает несколько слотов ring-buffer (_0, _1, _2)."""
        if not sys.platform.startswith("linux"):
            pytest.skip("Linux-only тест")

        base_name = "test_inspector_multislot"
        coll = 3
        created_shms: list[shared_memory.SharedMemory] = []

        # Создаём 3 слота
        for i in range(coll):
            shm = shared_memory.SharedMemory(name=f"{base_name}_{i}", create=True, size=512)
            shm.close()
            created_shms.append(shm)

        try:
            cleaned = cleanup_stale_shm(known_names=[base_name])
            assert len(cleaned) == coll, f"Ожидали {coll} очищенных, получили: {cleaned}"
            for i in range(coll):
                assert f"{base_name}_{i}" in cleaned
        finally:
            # Страховочный cleanup
            for i in range(coll):
                try:
                    leftover = shared_memory.SharedMemory(name=f"{base_name}_{i}", create=False)
                    leftover.close()
                    leftover.unlink()
                except Exception:
                    pass


# ===========================================================================
# Тест AppConfig.all_shm_names()
# ===========================================================================


class TestAppConfigAllShmNames:
    def test_all_shm_names_contains_known_keys(self):
        """AppConfig.all_shm_names() возвращает имена из memory всех процессов."""
        import sys

        # Убеждаемся что путь к фреймворку есть в sys.path
        root = Path(__file__).resolve().parent.parent.parent.parent  # Inspector_prototype
        modules = root / "multiprocess_framework" / "modules"
        for p in (root, modules):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))

        from multiprocess_prototype_v3.config.app import AppConfig

        app = AppConfig()
        names = app.all_shm_names()

        assert isinstance(names, list)
        assert len(names) > 0

        # Камера по умолчанию camera_id=0 → должен быть camera_0_frame
        assert "camera_0_frame" in names
        # Processor → processor_mask
        assert "processor_mask" in names
        # Renderer → rendered_frame, mask_frame
        assert "rendered_frame" in names
        assert "mask_frame" in names
        # "coll" никогда не должен попасть в имена
        assert "coll" not in names

    def test_all_shm_names_multi_camera(self):
        """all_shm_names() собирает имена для нескольких камер."""
        import sys

        root = Path(__file__).resolve().parent.parent.parent.parent
        modules = root / "multiprocess_framework" / "modules"
        for p in (root, modules):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))

        from multiprocess_prototype_v3.backend.processes.camera.config import CameraConfig
        from multiprocess_prototype_v3.config.app import AppConfig

        cameras = [CameraConfig(camera_id=i) for i in range(3)]
        app = AppConfig(cameras=cameras)
        names = app.all_shm_names()

        for i in range(3):
            assert f"camera_{i}_frame" in names

    def test_all_shm_names_no_duplicates(self):
        """all_shm_names() не содержит дубликатов."""
        import sys

        root = Path(__file__).resolve().parent.parent.parent.parent
        modules = root / "multiprocess_framework" / "modules"
        for p in (root, modules):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))

        from multiprocess_prototype_v3.config.app import AppConfig

        app = AppConfig()
        names = app.all_shm_names()
        assert len(names) == len(set(names)), f"Дубликаты в all_shm_names(): {names}"
