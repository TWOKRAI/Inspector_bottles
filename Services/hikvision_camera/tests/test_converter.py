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

    def test_letterbox_preserves_aspect_with_padding(self):
        """letterbox: 4:3 (640×480) → 16:9 (640×360) вписывает с сохранением аспекта
        и добивает чёрными полями слева/справа (pillarbox), НЕ растягивая (H2).

        scale = min(640/640, 360/480) = 0.75 → контент 480×360, центр по ширине,
        поля по 80px слева и справа.
        """
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)  # белый 4:3
        result = FrameConverter.resize(frame, 640, 360, mode="letterbox")

        assert result.shape == (360, 640, 3)
        # Поля слева/справа — чёрные (весь столбец)
        assert result[:, 0, :].sum() == 0, "левый столбец должен быть чёрным полем"
        assert result[:, -1, :].sum() == 0, "правый столбец должен быть чёрным полем"
        # Центр — белый контент
        assert result[180, 320, :].tolist() == [255, 255, 255]

    def test_letterbox_no_padding_when_aspect_matches(self):
        """letterbox при совпадении аспекта (4:3→4:3) = чистый ресайз без полей."""
        frame = np.full((480, 640, 3), 200, dtype=np.uint8)
        result = FrameConverter.resize(frame, 320, 240, mode="letterbox")

        assert result.shape == (240, 320, 3)
        # Полей нет — весь кадр заполнен контентом
        assert result.min() == 200 and result.max() == 200

    def test_stretch_mode_anamorphic(self):
        """stretch: явный анаморфный ресайз (заполняет всю цель, искажает геометрию)."""
        frame = np.full((480, 640, 3), 128, dtype=np.uint8)
        result = FrameConverter.resize(frame, 640, 360, mode="stretch")

        assert result.shape == (360, 640, 3)
        # Никаких чёрных полей — весь кадр заполнен (растянут)
        assert result.min() == 128

    def test_unknown_mode_falls_back_to_letterbox(self):
        """Неизвестный режим трактуется как letterbox (fail-safe)."""
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        result = FrameConverter.resize(frame, 640, 360, mode="bogus")

        assert result.shape == (360, 640, 3)
        # letterbox → есть чёрные поля по бокам
        assert result[:, 0, :].sum() == 0

    def test_letterbox_grayscale_2d(self):
        """letterbox корректно работает с 2D grayscale (без оси каналов)."""
        gray = np.full((480, 640), 255, dtype=np.uint8)
        result = FrameConverter.resize(gray, 640, 360, mode="letterbox")

        assert result.shape == (360, 640)
        assert result[:, 0].sum() == 0  # чёрное поле слева
