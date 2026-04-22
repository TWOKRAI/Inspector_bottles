"""Тесты для MemoryHandle."""

import sys

import pytest

from ..core.shared_resources_manager import SharedResourcesManager
from ..handles import MemoryHandle


SKIP_SHM = sys.platform == "darwin"
SKIP_REASON = "SharedMemory unreliable on macOS"

MEMORY_CONFIG = {
    "queues": {"system": {"maxsize": 10}},
    "memory": {
        "names": {"frame": (1, (4, 4, 3), "uint8")},
        "coll": 2,
    },
}


@pytest.fixture
def srm():
    s = SharedResourcesManager()
    s.initialize()
    s.register_process("cam", MEMORY_CONFIG)
    yield s
    s.shutdown()


@pytest.mark.skipif(SKIP_SHM, reason=SKIP_REASON)
class TestMemoryHandle:
    def test_memory_returns_handle(self, srm):
        handle = srm.for_process("cam")
        mem = handle.memory("frame")
        assert isinstance(mem, MemoryHandle)

    def test_memory_exists(self, srm):
        handle = srm.for_process("cam")
        assert handle.memory("frame").exists is True
        assert handle.memory("nonexistent").exists is False

    def test_find_free_index(self, srm):
        handle = srm.for_process("cam")
        idx = handle.memory("frame").find_free_index()
        assert idx is not None
        assert idx == 0

    def test_write_and_read(self, srm):
        import numpy as np

        handle = srm.for_process("cam")
        mem = handle.memory("frame")
        img = np.zeros((4, 4, 3), dtype=np.uint8)
        img[0, 0, 0] = 42
        result = mem.write([img], index=0)
        assert result is not None

        images = mem.read(index=0)
        assert images is not None
        assert len(images) >= 1
        assert images[0][0, 0, 0] == 42

    def test_release(self, srm):
        handle = srm.for_process("cam")
        mem = handle.memory("frame")
        mem.release(index=0)

    def test_repr(self, srm):
        mem = srm.for_process("cam").memory("frame")
        assert "cam" in repr(mem)
        assert "frame" in repr(mem)
