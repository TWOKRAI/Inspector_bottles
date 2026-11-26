"""H9 (находка F5 стенда волны 1): register настоящей камеры Hikvision называет драйвер `mvs`, а не `fake`."""

from __future__ import annotations

from Services.camera_device.registers_base import CameraDeviceRegisters
from Services.hikvision_camera.plugin.registers import HikvisionCameraRegisters


def test_hikvision_register_driver_is_mvs() -> None:
    assert HikvisionCameraRegisters().driver == "mvs"


def test_base_register_driver_still_fake() -> None:
    """Охранный: умолчание ядра не меняется — базовый плагин без вендора работает на fake."""
    assert CameraDeviceRegisters().driver == "fake"
