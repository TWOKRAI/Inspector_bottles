"""Контракт augment: фотометрия полным кадром, формы и базовые свойства."""

from __future__ import annotations

import numpy as np
import pytest

from Services.dataset_gen.core.augment import (
    apply_brightness_contrast,
    apply_color_temperature,
    apply_glare,
    apply_jpeg,
    apply_motion_blur,
    apply_photometric,
    make_motion_kernel,
)
from Services.dataset_gen.core.config import AugmentConfig


@pytest.fixture
def frame_f32() -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.uniform(40, 200, size=(64, 64, 3)).astype(np.float32)


class TestGlare:
    def test_brightens_center_not_corners(self, frame_f32):
        out = apply_glare(frame_f32, (32.0, 32.0), radius_px=15.0, intensity=80.0)
        assert out[32, 32].mean() > frame_f32[32, 32].mean() + 50
        assert out[0, 0].mean() == pytest.approx(frame_f32[0, 0].mean())


class TestMotionBlur:
    def test_kernel_normalized(self):
        kernel = make_motion_kernel(7, 30.0)
        assert kernel.sum() == pytest.approx(1.0)

    def test_blur_preserves_mean(self, frame_f32):
        out = apply_motion_blur(frame_f32, 7, 45.0)
        assert out.mean() == pytest.approx(frame_f32.mean(), rel=0.05)


class TestBrightnessContrastTemperature:
    def test_brightness_shifts_mean(self, frame_f32):
        out = apply_brightness_contrast(frame_f32, brightness=20.0, contrast=1.0)
        assert out.mean() == pytest.approx(frame_f32.mean() + 20.0, abs=0.5)

    def test_warm_shift_raises_red_lowers_blue(self, frame_f32):
        out = apply_color_temperature(frame_f32, shift=0.1)
        assert out[:, :, 0].mean() > frame_f32[:, :, 0].mean()
        assert out[:, :, 2].mean() < frame_f32[:, :, 2].mean()


class TestJpeg:
    def test_roundtrip_shape_and_dtype(self):
        frame = np.random.default_rng(1).integers(0, 255, (64, 64, 3), dtype=np.uint8)
        out = apply_jpeg(frame, quality=60)
        assert out.shape == frame.shape
        assert out.dtype == np.uint8


class TestApplyPhotometric:
    def test_all_disabled_is_identity(self):
        frame = np.random.default_rng(2).integers(0, 255, (48, 48, 3), dtype=np.uint8)
        cfg = AugmentConfig.model_validate(
            {
                name: {"enabled": False}
                for name in (
                    "brightness_contrast",
                    "gaussian_blur",
                    "motion_blur",
                    "noise",
                    "color_temperature",
                    "jpeg",
                    "glare",
                )
            }
        )
        out = apply_photometric(frame, cfg, np.random.default_rng(0))
        assert (out == frame).all()

    def test_output_shape_dtype_with_everything_on(self):
        frame = np.random.default_rng(3).integers(0, 255, (48, 48, 3), dtype=np.uint8)
        cfg = AugmentConfig.model_validate(
            {
                "motion_blur": {"enabled": True, "prob": 1.0},
                "jpeg": {"enabled": True, "prob": 1.0},
                "glare": {"enabled": True, "prob": 1.0},
                "gaussian_blur": {"prob": 1.0},
                "noise": {"prob": 1.0},
                "color_temperature": {"prob": 1.0},
                "brightness_contrast": {"prob": 1.0},
            }
        )
        out = apply_photometric(frame, cfg, np.random.default_rng(0))
        assert out.shape == frame.shape
        assert out.dtype == np.uint8
