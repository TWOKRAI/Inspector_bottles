# -*- coding: utf-8 -*-
"""Тесты FrameConverter: конвертация пикселей и resize."""

from __future__ import annotations

import numpy as np

from Services.hikvision_camera.core.converter import FrameConverter
from Services.hikvision_camera.sdk.constants import PixelType


class TestToBgr:
    """Тесты конвертации в BGR."""

    def test_bayer_to_bgr(self, sample_bayer_frame):
        """Bayer RG8 (2D) → 3-канальный BGR."""
        result = FrameConverter.to_bgr(sample_bayer_frame, PixelType.BAYER_RG8)

        assert result is not None
        assert result.ndim == 3
        assert result.shape[2] == 3
        # Высота и ширина сохраняются
        assert result.shape[0] == sample_bayer_frame.shape[0]
        assert result.shape[1] == sample_bayer_frame.shape[1]

    def test_gray_to_bgr(self, sample_bayer_frame):
        """Mono8 (2D grayscale) → 3-канальный BGR."""
        result = FrameConverter.to_bgr(sample_bayer_frame, PixelType.MONO8)

        assert result is not None
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_rgba_to_bgr(self, sample_rgba_frame):
        """RGBA (4 канала) → 3-канальный BGR."""
        result = FrameConverter.to_bgr(sample_rgba_frame, PixelType.RGBA8)

        assert result is not None
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_rgb_to_bgr(self, sample_bgr_frame):
        """RGB (3 канала) → BGR (каналы переставлены)."""
        result = FrameConverter.to_bgr(sample_bgr_frame, PixelType.RGB8)

        assert result is not None
        assert result.ndim == 3
        assert result.shape[2] == 3
        # Проверяем, что каналы действительно переставлены
        # BGR[..., 0] должен быть равен RGB[..., 2]
        np.testing.assert_array_equal(result[..., 0], sample_bgr_frame[..., 2])
        np.testing.assert_array_equal(result[..., 2], sample_bgr_frame[..., 0])

    def test_unsupported_format_1d(self):
        """1D массив → None (неподдерживаемый формат)."""
        frame_1d = np.zeros(100, dtype=np.uint8)
        result = FrameConverter.to_bgr(frame_1d, PixelType.UNDEFINED)

        assert result is None

    def test_unsupported_format_empty(self):
        """Пустой массив → None."""
        frame_empty = np.array([], dtype=np.uint8)
        result = FrameConverter.to_bgr(frame_empty, PixelType.BAYER_RG8)

        assert result is None

    def test_none_frame(self):
        """None вместо кадра → None."""
        result = FrameConverter.to_bgr(None, PixelType.BAYER_RG8)

        assert result is None

    def test_to_bgr_with_pixel_type_as_int(self, sample_bayer_frame):
        """Работает с числовым значением pixel_type (int), а не только enum."""
        # BAYER_RG8 как int
        result = FrameConverter.to_bgr(sample_bayer_frame, 17301513)

        assert result is not None
        assert result.ndim == 3
        assert result.shape[2] == 3

    def test_to_bgr_with_pixel_type_enum(self, sample_bayer_frame):
        """Работает с PixelType enum."""
        result = FrameConverter.to_bgr(sample_bayer_frame, PixelType.BAYER_RG8)

        assert result is not None
        assert result.ndim == 3

    def test_bgr_passthrough(self, sample_bgr_frame):
        """3-канальный кадр с неизвестным pixel_type → возвращается как есть."""
        result = FrameConverter.to_bgr(sample_bgr_frame, PixelType.UNDEFINED)

        assert result is not None
        assert result.ndim == 3
        assert result.shape[2] == 3
        # Тот же объект (без копирования)
        np.testing.assert_array_equal(result, sample_bgr_frame)

    def test_all_bayer_patterns(self, sample_bayer_frame):
        """Все Bayer-паттерны конвертируются в 3-канальный BGR."""
        bayer_types = [
            PixelType.BAYER_RG8,
            PixelType.BAYER_GR8,
            PixelType.BAYER_GB8,
            PixelType.BAYER_BG8,
        ]
        for pt in bayer_types:
            result = FrameConverter.to_bgr(sample_bayer_frame, pt)
            assert result is not None, f"Не сработал для {pt.name}"
            assert result.shape[2] == 3, f"Не 3 канала для {pt.name}"


class TestResize:
    """Тесты FrameConverter.resize."""

    def test_resize_same_size(self, sample_bgr_frame):
        """Resize на тот же размер — no-op (тот же объект)."""
        h, w = sample_bgr_frame.shape[:2]
        result = FrameConverter.resize(sample_bgr_frame, w, h)

        # Должен вернуть тот же объект (не копию)
        assert result is sample_bgr_frame

    def test_resize_different_size(self, sample_bgr_frame):
        """Resize на другой размер — реальный resize."""
        new_w, new_h = 320, 240
        result = FrameConverter.resize(sample_bgr_frame, new_w, new_h)

        assert result.shape[0] == new_h
        assert result.shape[1] == new_w
        assert result.shape[2] == 3  # Каналы сохраняются

    def test_resize_upscale(self, sample_bgr_frame):
        """Resize вверх — увеличение размера."""
        new_w, new_h = 1280, 960
        result = FrameConverter.resize(sample_bgr_frame, new_w, new_h)

        assert result.shape[0] == new_h
        assert result.shape[1] == new_w

    def test_resize_grayscale(self):
        """Resize работает для 2D (grayscale) кадра."""
        gray = np.zeros((100, 200), dtype=np.uint8)
        result = FrameConverter.resize(gray, 50, 25)

        assert result.shape == (25, 50)
