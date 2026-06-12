"""Контракт augment: фотометрия полным кадром, формы и базовые свойства."""

from __future__ import annotations

import numpy as np
import pytest

from Services.dataset_gen.core.augment import (
    apply_brightness_contrast,
    apply_channel_shift,
    apply_color_temperature,
    apply_gamma,
    apply_glare,
    apply_jpeg,
    apply_motion_blur,
    apply_occlusion,
    apply_photometric,
    apply_shadow,
    apply_vignette,
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
        # отключаем ВСЕ фотометрические блоки программно (не хардкодим список —
        # тест устойчив к добавлению новых аугментаций)
        cfg = AugmentConfig.model_validate({name: {"enabled": False} for name in AugmentConfig.model_fields})
        out = apply_photometric(frame, cfg, np.random.default_rng(0))
        assert (out == frame).all()

    def test_output_shape_dtype_with_everything_on(self):
        frame = np.random.default_rng(3).integers(0, 255, (48, 48, 3), dtype=np.uint8)
        # все фотометрические аугментации включены с prob=1 (геометрия не в проходе)
        photometric = {
            "brightness_contrast",
            "gamma",
            "vignette",
            "gaussian_blur",
            "motion_blur",
            "noise",
            "color_temperature",
            "channel_shift",
            "jpeg",
            "glare",
            "shadow",
            "occlusion",
        }
        cfg = AugmentConfig.model_validate({name: {"enabled": True, "prob": 1.0} for name in photometric})
        out = apply_photometric(frame, cfg, np.random.default_rng(0))
        assert out.shape == frame.shape
        assert out.dtype == np.uint8


class TestGamma:
    def test_gamma_gt1_darkens_midtones(self, frame_f32):
        out = apply_gamma(frame_f32, 2.0)
        assert out.mean() < frame_f32.mean()

    def test_gamma_1_is_identity(self, frame_f32):
        out = apply_gamma(frame_f32, 1.0)
        assert np.allclose(out, frame_f32, atol=0.5)


class TestVignette:
    def test_darkens_corners_keeps_center(self, frame_f32):
        out = apply_vignette(frame_f32, strength=0.5, radius_frac=0.3)
        center = out[28:36, 28:36].mean() / frame_f32[28:36, 28:36].mean()
        corner = out[:4, :4].mean() / frame_f32[:4, :4].mean()
        assert center > 0.97
        assert corner < 0.85


class TestChannelShift:
    def test_shifts_each_channel_independently(self, frame_f32):
        out = apply_channel_shift(frame_f32, (10.0, -5.0, 0.0))
        assert out[:, :, 0].mean() == pytest.approx(frame_f32[:, :, 0].mean() + 10.0, abs=0.1)
        assert out[:, :, 1].mean() == pytest.approx(frame_f32[:, :, 1].mean() - 5.0, abs=0.1)
        assert out[:, :, 2].mean() == pytest.approx(frame_f32[:, :, 2].mean(), abs=0.1)


class TestShadow:
    def test_darkens_far_side_keeps_near_side(self, frame_f32):
        # тень слева направо (angle=0): правый край темнее, левый почти не тронут
        out = apply_shadow(frame_f32, angle_deg=0.0, offset=0.5, strength=0.4, softness=0.2)
        left = out[:, :4].mean() / frame_f32[:, :4].mean()
        right = out[:, -4:].mean() / frame_f32[:, -4:].mean()
        assert left > 0.97
        assert right == pytest.approx(0.6, abs=0.05)

    def test_never_darkens_below_strength(self, frame_f32):
        out = apply_shadow(frame_f32, angle_deg=137.0, offset=0.3, strength=0.5, softness=0.3)
        assert (out >= frame_f32 * 0.5 - 1e-3).all()


class TestOcclusion:
    def test_rect_filled_rest_untouched(self, frame_f32):
        out = apply_occlusion(frame_f32, (10, 12, 8, 6), (5.0, 5.0, 5.0))
        assert (out[12:18, 10:18] == 5.0).all()
        assert (out[:12] == frame_f32[:12]).all()
        assert (out[:, :10] == frame_f32[:, :10]).all()

    def test_offscreen_rect_is_safe(self, frame_f32):
        out = apply_occlusion(frame_f32, (200, 200, 10, 10), (0.0, 0.0, 0.0))
        assert (out == frame_f32).all()
