"""Cleanup осиротевших SHM-сегментов.

Re-export из multiprocess_framework.modules.shared_resources_module (Phase 2.4).
"""
from multiprocess_framework.modules.shared_resources_module.buffers.cleanup import (
    cleanup_stale_shm,
)

__all__ = ["cleanup_stale_shm"]
