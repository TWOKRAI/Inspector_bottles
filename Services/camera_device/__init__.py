# -*- coding: utf-8 -*-
"""Общее ядро камер: контракт порта прибора и его фейк; сюда — менять порт, границу SDK и эмуляцию

Общее ядро камер: контракт порта прибора. Внешние модули зависят только от `interface.py`.
"""

from Services.camera_device.interface import (
    Binding,
    DeviceIdentity,
    DevicePort,
    DeviceSdk,
    ParamInfo,
    PortError,
    RawFrame,
)

__all__ = [
    "Binding",
    "DeviceIdentity",
    "DevicePort",
    "DeviceSdk",
    "ParamInfo",
    "PortError",
    "RawFrame",
]
