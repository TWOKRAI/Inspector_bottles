# -*- coding: utf-8 -*-
"""Ф7 G.9(b): AllocProfiler — профиль аллокаций/кадр через tracemalloc (soak-диагностика)."""

from __future__ import annotations

import tracemalloc

import pytest

from multiprocess_framework.modules.process_module.generic.alloc_profile import AllocProfiler


def test_per_frame_counts_allocations():
    prof = AllocProfiler()
    prof.start()
    try:
        prof.mark()
        # Аллоцируем заведомо: 100 кадров по списку 1000 int.
        held = []
        frames = 100
        for _ in range(frames):
            held.append([0] * 1000)
        stats = prof.per_frame(frames)
        assert stats["total_bytes"] > 0
        assert stats["bytes_per_frame"] > 0
        assert stats["blocks_per_frame"] > 0
        assert isinstance(stats["top"], list)
        assert len(held) == frames  # держим ссылку, чтобы не собралось до снимка
    finally:
        prof.stop()


def test_per_frame_requires_mark():
    prof = AllocProfiler()
    prof.start()
    try:
        with pytest.raises(RuntimeError):
            prof.per_frame(10)
    finally:
        prof.stop()


def test_stop_idempotent_and_respects_external_tracing():
    # Если tracemalloc уже трейсит (не мы включили) — stop его НЕ выключает.
    tracemalloc.start()
    try:
        prof = AllocProfiler()
        prof.start()  # уже трейсит → _started_here=False
        prof.stop()
        assert tracemalloc.is_tracing() is True  # чужой трейс не тронут
    finally:
        tracemalloc.stop()
    # Идемпотентность: повторный stop без start не падает.
    AllocProfiler().stop()
