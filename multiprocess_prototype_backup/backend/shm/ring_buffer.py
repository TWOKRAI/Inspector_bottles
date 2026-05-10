"""Ring-buffer для SHM кадров.

Re-export из multiprocess_framework.modules.shared_resources_module (Phase 2.4).
"""
from multiprocess_framework.modules.shared_resources_module.buffers.ring_buffer import (
    RingBufferReader,
    RingBufferWriter,
)

__all__ = ["RingBufferWriter", "RingBufferReader"]
