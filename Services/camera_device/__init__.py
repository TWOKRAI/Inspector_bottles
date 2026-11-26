# -*- coding: utf-8 -*-
"""Общее ядро камер: контракт порта прибора и его фейк; сюда — менять порт, границу SDK и эмуляцию

Общее ядро камер: контракт порта прибора. Внешние модули зависят только от `interface.py`.
"""

from Services.camera_device.interface import (
    AmbiguousDeviceError,
    Binding,
    DeviceIdentity,
    DeviceInfo,
    DevicePort,
    DeviceSdk,
    ParamInfo,
    PortError,
    RawFrame,
    entry_text,
    in_camera_subnet,
    select_device,
)

__all__ = [
    "AmbiguousDeviceError",
    "Binding",
    "DeviceIdentity",
    "DeviceInfo",
    "DevicePort",
    "DeviceSdk",
    "ParamInfo",
    "PortError",
    "RawFrame",
    "entry_text",
    "in_camera_subnet",
    "select_device",
]
