# -*- coding: utf-8 -*-
"""Ф7 G.7 (0.5) — метрика размера reader-кэша SHM-handle (наблюдаемость роста).

`ShmFrameReader.cache_size` → `FrameShmMiddleware.frame_handle_cache_size` →
`router.get_stats()["frame_handle_cache_size"]` → heartbeat `state.shm.cache_size`.
Под zero-copy эвикция отключена → на soak рост на инкарнацию = утечка handle
(резидуал G.5). Без handle-кэша (флаг off) кэш пуст → 0 (off = прежнее поведение).
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)


def _enable_handle_cache(monkeypatch) -> None:
    monkeypatch.setenv("FW_SHM_SEQLOCK", "1")
    monkeypatch.setenv("FW_SHM_OWNER_INCARNATION", "1")
    monkeypatch.setenv("FW_SHM_HANDLE_CACHE", "1")


class TestHandleCacheSizeMetric:
    def test_cache_size_grows_with_cross_process_read(self, monkeypatch):
        """С handle-кэшем чтение кадра оседает handle'ом в кэше → cache_size растёт."""
        _enable_handle_cache(monkeypatch)
        writer = FrameShmMiddleware(MemoryManager(), owner="cam0", slot="output_frames", coll=2)
        reader = FrameShmMiddleware(MemoryManager(), owner="reader", slot="unused")
        try:
            assert reader.frame_handle_cache_size == 0  # ещё ничего не читали
            out = writer.strip_and_write({"frame": np.full((16, 16, 3), 1, np.uint8)})
            reader.restore_frame({"data": out})
            # Один сегмент открыт и закэширован.
            assert reader.frame_handle_cache_size == 1
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()
            # После teardown кэш очищен.
            assert reader.frame_handle_cache_size == 0

    def test_cache_size_zero_without_handle_cache(self, monkeypatch):
        """Флаг off: сегмент открывается/закрывается на кадр, кэш пуст → 0 (бит-в-бит)."""
        monkeypatch.delenv("FW_SHM_HANDLE_CACHE", raising=False)
        monkeypatch.setenv("FW_SHM_SEQLOCK", "1")
        monkeypatch.setenv("FW_SHM_OWNER_INCARNATION", "1")
        writer = FrameShmMiddleware(MemoryManager(), owner="cam0", slot="output_frames", coll=2)
        reader = FrameShmMiddleware(MemoryManager(), owner="reader", slot="unused")
        try:
            out = writer.strip_and_write({"frame": np.full((16, 16, 3), 1, np.uint8)})
            reader.restore_frame({"data": out})
            assert reader.frame_handle_cache_size == 0
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()
