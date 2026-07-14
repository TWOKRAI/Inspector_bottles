"""Platform — платформенные операции SharedMemory."""

from .shm import (
    cleanup_known_shm_at_startup,
    cleanup_stale_shm,
    close_shm,
    create_shm_block,
    create_shm_blocks,
    extract_memory_region_names,
    is_posix,
    is_windows,
    open_shm_block,
)

__all__ = [
    "cleanup_known_shm_at_startup",
    "cleanup_stale_shm",
    "close_shm",
    "create_shm_block",
    "create_shm_blocks",
    "extract_memory_region_names",
    "is_posix",
    "is_windows",
    "open_shm_block",
]
