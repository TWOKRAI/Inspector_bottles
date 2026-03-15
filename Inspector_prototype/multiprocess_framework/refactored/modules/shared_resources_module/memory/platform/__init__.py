"""Platform — платформенные операции SharedMemory."""

from .shm import (
    cleanup_stale_shm,
    close_shm,
    create_shm_block,
    create_shm_blocks,
    is_posix,
    is_windows,
    open_shm_block,
)

__all__ = [
    "cleanup_stale_shm",
    "close_shm",
    "create_shm_block",
    "create_shm_blocks",
    "is_posix",
    "is_windows",
    "open_shm_block",
]
