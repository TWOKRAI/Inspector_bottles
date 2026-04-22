# multiprocess_prototype\tests\test_stage0.py
"""
Тесты для Этапа 0 — инфраструктура (FrameGenerator, configs).
"""

import pytest


def test_frame_generator():
    """FrameGenerator генерирует кадры правильной формы."""
    from multiprocess_prototype.utils.frame_generator import FrameGenerator

    gen = FrameGenerator(640, 480)
    frame = gen.generate_frame()

    assert frame.shape == (480, 640, 3)
    assert frame.dtype.name == "uint8"
    assert gen.frame_count == 1

    frame2 = gen.generate_frame()
    assert gen.frame_count == 2
    assert frame2.shape == frame.shape


def test_configs():
    """Все конфиги создаются с дефолтными значениями."""
    from multiprocess_prototype.backend.configs import (
        CameraConfig,
        ProcessorConfig,
        RendererConfig,
        RobotConfig,
        GuiConfig,
    )

    c = CameraConfig()
    assert c.fps == 25
    assert c.resolution_width == 640
    assert c.resolution_height == 480
    assert c.use_simulator is False

    p = ProcessorConfig()
    assert p.min_area == 500
    assert p.color_lower == [0, 0, 150]
    assert p.color_upper == [100, 100, 255]

    r = RendererConfig()
    assert r.output_dir == "./output_frames"
    assert r.draw_bboxes is True

    rb = RobotConfig()
    assert rb.log_file == "./robot_actions.log"

    g = GuiConfig()
    assert g.window_width == 1024
    assert g.poll_interval_ms == 16
