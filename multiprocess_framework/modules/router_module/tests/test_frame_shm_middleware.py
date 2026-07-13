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


class TestFrameBoundaryCounter:
    """Ф7 G.6: счётчик границ процесса на кадр (frame_hops) + callback в router."""

    def test_strip_and_write_increments_frame_hops(self):
        mw = _mw()
        item = {"frame": _frame(600, 800)}
        out = mw.strip_and_write(item)
        assert out["frame_hops"] == 1
        # Повторный "hop" того же item (симуляция второго звена pipeline'а) —
        # счётчик накапливается, а не сбрасывается.
        out["frame"] = _frame(600, 800)  # следующий узел снова кладёт кадр в SHM
        out2 = mw.strip_and_write(out)
        assert out2["frame_hops"] == 2

    def test_strip_and_write_increments_on_pickle_fallback(self):
        """Кадр без SHM (memory_manager=None) всё равно уходит через IPC (pickle) —
        граница должна считаться, а не только на «честном» SHM-пути."""
        mw = FrameShmMiddleware(memory_manager=None, owner="test_owner", slot="output_frames")
        item = {"frame": _frame(600, 800)}
        out = mw.strip_and_write(item)
        assert "shm_actual_name" not in out  # ушёл через pickle-fallback
        assert out["frame"] is not None  # frame не вырезан (pickle-путь)
        assert out["frame_hops"] == 1

    def test_strip_and_write_no_frame_does_not_increment(self):
        mw = _mw()
        item = {"seq_id": 1}  # нет frame — не боундари
        out = mw.strip_and_write(item)
        assert "frame_hops" not in out

    def test_strip_and_write_calls_on_boundary_cross(self):
        calls: list = []
        mw = FrameShmMiddleware(
            MemoryManager(),
            owner="test_owner",
            slot="output_frames",
            coll=3,
            on_boundary_cross=lambda: calls.append(1),
        )
        mw.strip_and_write({"frame": _frame(600, 800)})
        mw.strip_and_write({"frame": _frame(600, 800)})
        assert len(calls) == 2

    def test_on_send_increments_frame_hops_in_data(self):
        mw = _mw()
        msg = {"frame": _frame(600, 800)}
        out = mw.on_send(msg)
        assert out["data"]["frame_hops"] == 1

    def test_on_send_without_memory_manager_still_increments(self):
        """Без memory_manager frame остаётся в msg (pickle) — граница всё равно
        реальна (кадр уйдёт через IPC как есть), счётчик должен расти."""
        mw = FrameShmMiddleware(memory_manager=None, owner="test_owner", slot="output_frames")
        msg = {"frame": _frame(600, 800)}
        out = mw.on_send(msg)
        assert out["frame"] is not None
        assert out["data"]["frame_hops"] == 1

    def test_on_send_no_frame_does_not_increment(self):
        mw = _mw()
        out = mw.on_send({"command": "noop"})
        assert "data" not in out

    def test_on_boundary_cross_default_is_noop(self):
        """Без callback (обратная совместимость) — не падает."""
        mw = FrameShmMiddleware(MemoryManager(), owner="test_owner", slot="output_frames")
        out = mw.strip_and_write({"frame": _frame(600, 800)})
        assert out["frame_hops"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
