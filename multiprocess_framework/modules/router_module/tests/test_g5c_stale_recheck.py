# -*- coding: utf-8 -*-
"""Ф7 G.5.c — post-use re-check zero-copy view (В1-пол by-construction).

После того как consumer дочитал view, сверяем поколение слота с поколением на момент
чтения. Совпало → view пережил обработку. Разошлось (writer обернул кольцо и
перезаписал слот под живым view) → drop результата (счётчик frame_stale_drops), НЕ
порча. Поколение монотонно → любой wrap обнаруживается надёжно.
"""

from __future__ import annotations

import numpy as np

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)


def _enable_zero_copy(monkeypatch) -> None:
    monkeypatch.setenv("FW_SHM_SEQLOCK", "1")
    monkeypatch.setenv("FW_SHM_OWNER_INCARNATION", "1")
    monkeypatch.setenv("FW_SHM_HANDLE_CACHE", "1")
    monkeypatch.setenv("FW_SHM_ZERO_COPY", "1")


class TestMiddlewareRecheck:
    def test_valid_immediately_then_stale_after_wrap(self, monkeypatch):
        """Сразу после чтения view валиден; после оборота кольца (перезапись слота) —
        stale (drift поколения) → drop + счётчик."""
        _enable_zero_copy(monkeypatch)
        writer = FrameShmMiddleware(MemoryManager(), owner="cam0", slot="output_frames", coll=2)
        reader = FrameShmMiddleware(MemoryManager(), owner="reader", slot="unused")
        try:
            out = writer.strip_and_write({"frame": np.full((16, 16, 3), 1, np.uint8)})
            frame = reader.restore_frame({"data": out})["frame"]
            name = out["_shm_view_name"]
            gen = out["_shm_view_generation"]
            del frame  # дропаем view (backing mmap можно трогать)

            # Сразу после чтения — слот не тронут → валиден, без drop.
            assert reader.frame_view_valid(name, gen) is True
            assert reader.frame_stale_drops == 0

            # Writer оборачивает кольцо coll=2: две записи возвращают его на slot name.
            writer.strip_and_write({"frame": np.full((16, 16, 3), 2, np.uint8)})
            writer.strip_and_write({"frame": np.full((16, 16, 3), 3, np.uint8)})

            # Слот перезаписан под тем поколением → drift → stale drop.
            assert reader.frame_view_valid(name, gen) is False
            assert reader.frame_stale_drops == 1
        finally:
            reader.close_handle_cache()
            writer.release_owned_memory()

    def test_negative_generation_is_invalid(self, monkeypatch):
        """gen<0 (view без seqlock — не должно происходить) → консервативно невалиден."""
        _enable_zero_copy(monkeypatch)
        reader = FrameShmMiddleware(MemoryManager(), owner="r", slot="s")
        assert reader.frame_view_valid("any", -1) is False
        assert reader.frame_stale_drops == 1

    def test_unknown_name_is_invalid(self, monkeypatch):
        """handle не в кэше (эвикция/смена имени) → сегмент мог уехать → drop."""
        _enable_zero_copy(monkeypatch)
        reader = FrameShmMiddleware(MemoryManager(), owner="r", slot="s")
        assert reader.frame_view_valid("nonexistent_segment", 2) is False
        assert reader.frame_stale_drops == 1
