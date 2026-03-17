"""Unit-тесты fps_module."""

import time
import pytest

from Utils.fps_module import FrameFPS, RingBufferFPS, AverageFPS, FPSProvider


class TestFrameFPS:
    def test_init_invalid_interval(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            FrameFPS(interval=0)
        with pytest.raises(ValueError, match="positive"):
            FrameFPS(interval=-1.0)

    def test_fps_starts_zero(self) -> None:
        fps = FrameFPS(interval=1.0)
        assert fps.fps == 0.0
        assert fps.get_fps() == 0.0

    def test_update_returns_zero_until_interval(self) -> None:
        fps = FrameFPS(interval=10.0)
        for _ in range(5):
            assert fps.update() == 0.0

    def test_update_returns_fps_after_interval(self) -> None:
        fps = FrameFPS(interval=0.05)
        result = 0.0
        for _ in range(200):
            result = fps.update()
            if result > 0:
                break
            time.sleep(0.001)
        assert result > 0

    def test_reset(self) -> None:
        fps = FrameFPS(interval=1.0)
        fps.update()
        fps.reset()
        assert fps.fps == 0.0

    def test_fps_provider_protocol(self) -> None:
        fps = FrameFPS()
        assert isinstance(fps, FPSProvider)


class TestRingBufferFPS:
    def test_init_invalid_params(self) -> None:
        with pytest.raises(ValueError):
            RingBufferFPS(window_seconds=0)
        with pytest.raises(ValueError):
            RingBufferFPS(max_samples=1)

    def test_fps_after_few_frames(self) -> None:
        fps = RingBufferFPS(window_seconds=1.0)
        for _ in range(10):
            fps.update()
        assert fps.fps >= 0

    def test_reset(self) -> None:
        fps = RingBufferFPS(window_seconds=1.0)
        fps.update()
        fps.reset()
        assert fps.fps == 0.0


class TestAverageFPS:
    def test_init_invalid_interval(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            AverageFPS(interval=0)

    def test_average_fps_without_window_equals_current(self) -> None:
        fps = AverageFPS(interval=0.05, average_samples=None)
        for _ in range(200):
            fps.update()
            time.sleep(0.001)
        assert fps.average_fps == fps.fps or (fps.fps == 0 and fps.average_fps == 0)

    def test_average_fps_accumulates(self) -> None:
        fps = AverageFPS(interval=0.02, average_samples=50)
        for _ in range(100):
            fps.update()
            time.sleep(0.01)
        assert fps.average_fps >= 0
        assert fps.fps >= 0
