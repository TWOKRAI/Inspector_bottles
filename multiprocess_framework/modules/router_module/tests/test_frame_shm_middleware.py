# -*- coding: utf-8 -*-
"""Тесты FrameShmMiddleware — Claim Check frame↔SHM, в т.ч. переаллокация при resize.

Ключевой инвариант (resize-safe): когда кадр становится больше выделенного блока
(увеличили ROI / сменили разрешение), middleware ПЕРЕаллоцирует SHM под новый
размер и продолжает писать через SHM (а не сваливается в вечный pickle-fallback).
Любой размер кадра восстанавливается на приёме корректно.
"""

from __future__ import annotations

import numpy as np
import pytest

from multiprocess_framework.modules.router_module.middleware.frame_shm_middleware import (
    FrameShmMiddleware,
)
from multiprocess_framework.modules.shared_resources_module.memory.core.manager import (
    MemoryManager,
)


def _mw() -> FrameShmMiddleware:
    return FrameShmMiddleware(MemoryManager(), owner="test_owner", slot="output_frames", coll=3)


def _frame(h: int, w: int, val: int = 50) -> np.ndarray:
    return np.full((h, w, 3), val, dtype=np.uint8)


def _roundtrip(mw: FrameShmMiddleware, frame: np.ndarray) -> tuple[bool, np.ndarray | None]:
    """strip_and_write → restore_frame. Возвращает (через_shm, восстановленный_кадр)."""
    out = mw.strip_and_write({"frame": frame.copy(), "seq_id": 1})
    via_shm = "shm_actual_name" in out
    restored = mw.restore_frame({"data": out}).get("frame")
    return via_shm, restored


class TestBasicRoundtrip:
    def test_first_frame_via_shm(self):
        mw = _mw()
        via_shm, restored = _roundtrip(mw, _frame(600, 800))
        assert via_shm is True
        assert restored is not None and restored.shape == (600, 800, 3)

    def test_smaller_frame_fits_existing_block(self):
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        via_shm, restored = _roundtrip(mw, _frame(600, 80))  # меньше — влезает
        assert via_shm is True
        assert restored is not None and restored.shape == (600, 80, 3)


class TestResizeReallocation:
    """Регресс: рост кадра → переаллокация → SHM (не pickle), размер корректен."""

    def test_grow_reallocates_and_stays_on_shm(self):
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        # Кадр вырос за пределы блока (увеличили ROI) — должна сработать переаллокация.
        via_shm, restored = _roundtrip(mw, _frame(1080, 1440, val=99))
        assert via_shm is True, "после роста кадр должен идти через SHM (переаллокация), а не pickle"
        assert restored is not None and restored.shape == (1080, 1440, 3)
        assert mw._alloc_shape == (1080, 1440, 3)

    def test_grow_then_smaller_all_via_shm_correct_size(self):
        mw = _mw()
        sizes = [(600, 800), (1080, 1440), (600, 801), (600, 80), (1200, 1600)]
        for h, w in sizes:
            via_shm, restored = _roundtrip(mw, _frame(h, w))
            assert via_shm is True, f"{h}x{w} должен идти через SHM"
            assert restored is not None and restored.shape == (h, w, 3), f"размер {h}x{w} искажён"

    def test_capacity_grows_only_never_shrinks(self):
        mw = _mw()
        _roundtrip(mw, _frame(1080, 1440))
        _roundtrip(mw, _frame(600, 800))  # меньше — ёмкость НЕ должна уменьшиться
        assert mw._alloc_shape == (1080, 1440, 3)

    def test_width_plus_one_does_not_break(self):
        """Точный кейс владельца: ROI 800→801 не ломает кадр (раньше → полный кадр)."""
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        via_shm, restored = _roundtrip(mw, _frame(600, 801))
        assert restored is not None and restored.shape == (600, 801, 3)
        assert via_shm is True


class TestFrameFitsHelper:
    def test_fits_within_capacity(self):
        mw = _mw()
        _roundtrip(mw, _frame(1080, 1440))
        assert mw._frame_fits(_frame(600, 800)) is True
        assert mw._frame_fits(_frame(1080, 1440)) is True

    def test_does_not_fit_when_larger(self):
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        assert mw._frame_fits(_frame(600, 801)) is False  # шире → не влезает
        assert mw._frame_fits(_frame(601, 800)) is False  # выше → не влезает

    def test_dtype_change_does_not_fit(self):
        mw = _mw()
        _roundtrip(mw, _frame(600, 800))
        other = np.zeros((600, 800, 3), dtype=np.float32)
        assert mw._frame_fits(other) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
