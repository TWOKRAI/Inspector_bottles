"""Unit-тесты для FrameThrottleMiddleware (Phase 6, Task 6.2)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from multiprocess_prototype.backend.routing.throttle_middleware import FrameThrottleMiddleware


class TestFrameThrottleMiddleware:
    def test_no_limit_passes_all(self):
        """Канал без лимита — все сообщения проходят."""
        mw = FrameThrottleMiddleware()
        msg = {"channel": "some_channel", "data": "frame"}
        # Несколько подряд — все должны пройти
        for _ in range(5):
            assert mw.on_send(msg) is not None

    def test_first_frame_always_passes(self):
        """Первый кадр для канала с лимитом всегда проходит."""
        mw = FrameThrottleMiddleware({"ch": 10})
        msg = {"channel": "ch", "data": "frame"}
        with patch(
            "multiprocess_prototype.backend.routing.throttle_middleware.time"
        ) as mock_time:
            mock_time.monotonic.return_value = 0.0
            result = mw.on_send(msg)
        assert result is not None

    def test_zero_fps_blocks_all(self):
        """fps_limit=0 → блокировать все кадры."""
        mw = FrameThrottleMiddleware({"ch": 0})
        msg = {"channel": "ch", "data": "frame"}
        assert mw.on_send(msg) is None
        assert mw.on_send(msg) is None

    def test_negative_fps_passes_all(self):
        """fps_limit=-1 → пропускать все кадры без ограничений."""
        mw = FrameThrottleMiddleware({"ch": -1})
        msg = {"channel": "ch", "data": "frame"}
        for _ in range(5):
            assert mw.on_send(msg) is not None

    def test_set_fps_limit_runtime(self):
        """set_fps_limit работает после создания — канал начинает троттлиться."""
        mw = FrameThrottleMiddleware()
        mw.set_fps_limit("ch", 0)  # блокировать все
        msg = {"channel": "ch", "data": "frame"}
        assert mw.on_send(msg) is None

    def test_remove_fps_limit(self):
        """remove_fps_limit → канал пропускает все кадры."""
        mw = FrameThrottleMiddleware({"ch": 0})
        mw.remove_fps_limit("ch")
        msg = {"channel": "ch", "data": "frame"}
        assert mw.on_send(msg) is not None

    def test_clear(self):
        """clear() убирает все лимиты — все каналы начинают пропускать кадры."""
        mw = FrameThrottleMiddleware({"ch1": 0, "ch2": 0})
        mw.clear()
        assert mw.on_send({"channel": "ch1", "data": "x"}) is not None
        assert mw.on_send({"channel": "ch2", "data": "x"}) is not None

    def test_throttling_drops_frames(self):
        """Кадры, пришедшие до истечения min_interval, дропаются."""
        mw = FrameThrottleMiddleware({"ch": 10})  # 10 fps → interval = 0.1s
        msg = {"channel": "ch", "data": "frame"}

        with patch(
            "multiprocess_prototype.backend.routing.throttle_middleware.time"
        ) as mock_time:
            mock_time.monotonic.return_value = 0.0
            assert mw.on_send(msg) is not None  # первый кадр — проходит

            mock_time.monotonic.return_value = 0.05  # 50ms < 100ms
            assert mw.on_send(msg) is None  # дроп

            mock_time.monotonic.return_value = 0.11  # 110ms > 100ms
            assert mw.on_send(msg) is not None  # интервал истёк — проходит
