# -*- coding: utf-8 -*-
"""Тесты констант и enum PixelType."""

from __future__ import annotations

from Services.hikvision_camera.sdk.constants import (
    PixelType,
    MV_GIGE_DEVICE,
    MV_USB_DEVICE,
)

# MV_OK живёт в errors.py, а не в constants.py. Раньше constants реэкспортировал
# его строкой `from .errors import MV_OK  # реэкспорт для удобства`, но ruff --fix
# снёс её как F401 (unused import) — коммит 6a37c470, 2026-05-14. С тех пор этот
# файл не собирался, роняя collection всего каталога Services/. Импортируем из
# настоящего дома символа: явный путь переживает авто-фиксы линтера.
# Не через фасад `sdk/__init__`: тот тянет bindings и бинарный SDK.
from Services.hikvision_camera.sdk.errors import MV_OK


class TestPixelType:
    """Тесты перечисления PixelType."""

    def test_pixel_type_bayer_rg8_value(self):
        """PixelType.BAYER_RG8 имеет конкретное числовое значение SDK."""
        assert PixelType.BAYER_RG8 == 17301513

    def test_pixel_type_mono8_value(self):
        """PixelType.MONO8 имеет конкретное числовое значение SDK."""
        assert PixelType.MONO8 == 17301505

    def test_pixel_type_from_value(self):
        """Можно создать PixelType из числового значения."""
        pt = PixelType(17301513)
        assert pt == PixelType.BAYER_RG8
        assert pt.name == "BAYER_RG8"

    def test_pixel_type_is_int(self):
        """PixelType — IntEnum, можно использовать как int."""
        assert isinstance(PixelType.BAYER_RG8, int)
        # Арифметика с int работает
        assert PixelType.BAYER_RG8 + 0 == 17301513

    def test_pixel_type_rgb_bgr(self):
        """RGB8 и BGR8 имеют разные значения."""
        assert PixelType.RGB8 != PixelType.BGR8
        assert PixelType.RGB8 == 35127316
        assert PixelType.BGR8 == 35127317

    def test_pixel_type_rgba(self):
        """RGBA8 — 4-канальный формат."""
        assert PixelType.RGBA8 == 35651606

    def test_pixel_type_undefined(self):
        """UNDEFINED = -1 для неопределённого формата."""
        assert PixelType.UNDEFINED == -1


class TestDeviceTypes:
    """Тесты констант типов устройств."""

    def test_gige_device_value(self):
        """MV_GIGE_DEVICE = 1."""
        assert MV_GIGE_DEVICE == 0x00000001

    def test_usb_device_value(self):
        """MV_USB_DEVICE = 4."""
        assert MV_USB_DEVICE == 0x00000004

    def test_mv_ok_reexport(self):
        """MV_OK реэкспортирован из errors для удобства."""
        assert MV_OK == 0
