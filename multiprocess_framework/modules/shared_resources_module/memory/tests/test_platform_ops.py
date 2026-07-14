"""
Тесты platform_ops.py — платформенные операции SharedMemory.

На macOS SharedMemory может работать нестабильно — тесты помечены skip.
"""

import platform
import pytest

from ..platform import (
    cleanup_stale_shm,
    create_shm_block,
    create_shm_blocks,
    close_shm,
    extract_memory_region_names,
    is_posix,
    is_windows,
    open_shm_block,
)

# SharedMemory на macOS (M1/M2) может быть нестабильным
SKIP_MACOS = platform.system() == "Darwin"


@pytest.mark.skipif(SKIP_MACOS, reason="SharedMemory unreliable on macOS")
class TestPlatformHelpers:
    def test_is_windows(self):
        assert is_windows() == (platform.system() == "Windows")

    def test_is_posix(self):
        assert is_posix() == (platform.system() in ("Linux", "Darwin"))


@pytest.mark.skipif(SKIP_MACOS, reason="SharedMemory unreliable on macOS")
class TestCreateShmBlock:
    def test_create_and_close(self):
        shm = create_shm_block("test_platform_ops_1", 1024)
        assert shm is not None
        assert shm.size >= 1024
        close_shm(shm, unlink=is_posix())

    def test_cleanup_stale_noop_on_existing(self):
        shm = create_shm_block("test_platform_ops_2", 256)
        assert shm is not None
        close_shm(shm, unlink=is_posix())


@pytest.mark.skipif(SKIP_MACOS, reason="SharedMemory unreliable on macOS")
class TestCreateShmBlocks:
    def test_create_multiple(self):
        blocks = create_shm_blocks("test_platform_ops_multi", 512, 2)
        assert blocks is not None
        assert len(blocks) == 2
        for shm in blocks:
            close_shm(shm, unlink=is_posix())

    def test_recreate_with_live_segment_succeeds_fresh(self):
        """Повторный create при ЖИВОМ старом сегменте не падает (свежая инкарнация).

        Регресс-гард hot-swap (Windows «File exists camera_0_frame_PID_0»): старый
        сегмент держится (handle ещё открыт), второй create того же base должен
        пересоздать со свежим именем, а не упасть FileExistsError.
        """
        first = create_shm_blocks("test_platform_ops_recreate", 256, 1)
        assert first is not None
        # Старый ещё ЖИВ (handle открыт) — имитируем переходное окно hot-swap.
        second = create_shm_blocks("test_platform_ops_recreate", 256, 1)
        assert second is not None, "повторный create должен дать свежую инкарнацию"
        # Имена различаются → нет коллизии
        assert second[0].name != first[0].name
        for shm in (*first, *second):
            close_shm(shm, unlink=is_posix())


@pytest.mark.skipif(SKIP_MACOS, reason="SharedMemory unreliable on macOS")
class TestOpenShmBlock:
    def test_open_existing(self):
        shm1 = create_shm_block("test_platform_ops_open", 128)
        shm2 = open_shm_block(shm1.name)
        assert shm2 is not None
        assert shm2.name == shm1.name
        close_shm(shm2, unlink=False)
        close_shm(shm1, unlink=is_posix())

    def test_open_nonexistent_returns_none(self):
        result = open_shm_block("nonexistent_shm_name_xyz_12345")
        assert result is None


class TestCleanupStaleShm:
    def test_cleanup_nonexistent_no_raise(self):
        cleanup_stale_shm("nonexistent_stale_xyz")


class TestExtractMemoryRegionNames:
    """Ф7 G.3 M8a: базовые имена memory-регионов из processes_config — источник
    ПРЕФИКСОВ для cleanup_orphaned_by_prefix (вместо хардкода ["output_frames"])."""

    def test_extracts_names_from_nested_names_format(self):
        cfg = {
            "camera": {"memory": {"names": {"camera_frame": (1, (600, 800, 3), "uint8")}, "coll": 2}},
        }
        assert extract_memory_region_names(cfg) == ["camera_frame"]

    def test_extracts_names_from_flat_format(self):
        cfg = {
            "camera": {"memory": {"camera_frame": (1, (600, 800, 3), "uint8"), "coll": 2}},
        }
        assert extract_memory_region_names(cfg) == ["camera_frame"]

    def test_extracts_from_multiple_processes_without_duplicates(self):
        cfg = {
            "camera_a": {"memory": {"names": {"camera_frame": (1, (600, 800, 3), "uint8")}, "coll": 2}},
            "camera_b": {"memory": {"names": {"camera_frame": (1, (600, 800, 3), "uint8")}}},
            "worker": {"memory": {"names": {"worker_scratch": (1, (32, 32, 3), "uint8")}}},
        }
        result = extract_memory_region_names(cfg)
        assert result.count("camera_frame") == 1
        assert "worker_scratch" in result
        assert len(result) == 2

    def test_process_without_memory_section_ignored(self):
        cfg = {"gui": {"class": "GuiProcess"}}
        assert extract_memory_region_names(cfg) == []

    def test_empty_or_none_config_returns_empty(self):
        assert extract_memory_region_names({}) == []
        assert extract_memory_region_names(None) == []

    def test_malformed_memory_section_is_safe(self):
        cfg = {"camera": {"memory": "not-a-dict"}, "other": "not-a-dict-either"}
        assert extract_memory_region_names(cfg) == []
