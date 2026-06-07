# -*- coding: utf-8 -*-
"""Тесты discovery: DeviceInfo dataclass и enum_devices."""

from __future__ import annotations

import pytest
from dataclasses import FrozenInstanceError

from unittest.mock import patch

from Services.hikvision_camera.core.discovery import DeviceInfo, enum_devices


class TestDeviceInfo:
    """Тесты dataclass DeviceInfo."""

    def test_device_info_creation(self):
        """DeviceInfo создаётся с правильными полями."""
        info = DeviceInfo(
            index=0,
            device_type="GigE",
            user_name="TestCam",
            model_name="MV-CE060-10GC",
            serial="192.168.1.100",
            display_name="[0] GigE: TestCam MV-CE060-10GC (192.168.1.100)",
        )

        assert info.index == 0
        assert info.device_type == "GigE"
        assert info.user_name == "TestCam"
        assert info.model_name == "MV-CE060-10GC"
        assert info.serial == "192.168.1.100"
        assert "TestCam" in info.display_name

    def test_device_info_to_dict(self):
        """to_dict() возвращает словарь со всеми полями."""
        info = DeviceInfo(
            index=1,
            device_type="USB",
            user_name="USBCam",
            model_name="MV-CE200-10UC",
            serial="ABC123",
            display_name="[1] USB: USBCam",
        )

        d = info.to_dict()

        assert isinstance(d, dict)
        assert d["index"] == 1
        assert d["device_type"] == "USB"
        assert d["user_name"] == "USBCam"
        assert d["model_name"] == "MV-CE200-10UC"
        assert d["serial"] == "ABC123"
        assert d["display_name"] == "[1] USB: USBCam"
        # Dict at Boundary: все ключи — строки
        assert all(isinstance(k, str) for k in d.keys())

    def test_device_info_frozen(self):
        """Frozen dataclass — нельзя менять атрибуты после создания."""
        info = DeviceInfo(
            index=0,
            device_type="GigE",
            user_name="Cam",
            model_name="Model",
            serial="SN001",
            display_name="[0] GigE: Cam",
        )

        with pytest.raises(FrozenInstanceError):
            info.index = 5  # type: ignore[misc]


class TestEnumDevices:
    """Тесты функции enum_devices."""

    def test_enum_devices_no_sdk(self):
        """SDK недоступен → пустой список."""
        with patch("Services.hikvision_camera.core.discovery.SDK_AVAILABLE", False):
            result = enum_devices()

        assert result == []
        assert isinstance(result, list)
