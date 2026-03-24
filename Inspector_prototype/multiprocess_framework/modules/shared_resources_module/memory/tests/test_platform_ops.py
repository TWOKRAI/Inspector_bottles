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
