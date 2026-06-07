# -*- coding: utf-8 -*-
"""
Обнаружение камер Hikvision (GigE / USB).

Возвращает типизированные DeviceInfo dataclass вместо сырых dict.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER
from dataclasses import dataclass, asdict

from hikvision_camera.sdk.bindings import MvCamera, SDK_AVAILABLE
from hikvision_camera.sdk.structures import (
    MV_CC_DEVICE_INFO,
    MV_CC_DEVICE_INFO_LIST,
)
from hikvision_camera.sdk.constants import MV_GIGE_DEVICE, MV_USB_DEVICE
from hikvision_camera.sdk.errors import check_sdk_error, SdkError


@dataclass(frozen=True)
class DeviceInfo:
    """Информация об обнаруженной камере."""

    index: int
    device_type: str  # "GigE" | "USB" | "Unknown"
    user_name: str
    model_name: str
    serial: str
    display_name: str

    def to_dict(self) -> dict:
        """Конвертация в dict (Dict at Boundary)."""
        return asdict(self)


def _parse_gige_device(index: int, mvcc: MV_CC_DEVICE_INFO) -> DeviceInfo:
    """Парсинг информации GigE-устройства."""
    user_name = ""
    model_name = ""

    try:
        user_name = ctypes.cast(
            mvcc.SpecialInfo.stGigEInfo.chUserDefinedName,
            ctypes.c_char_p,
        ).value.decode("gbk", errors="replace")
    except Exception:
        pass

    try:
        model_name = ctypes.cast(
            mvcc.SpecialInfo.stGigEInfo.chModelName,
            ctypes.c_char_p,
        ).value.decode("gbk", errors="replace")
    except Exception:
        pass

    nip = mvcc.SpecialInfo.stGigEInfo.nCurrentIp
    serial = f"{(nip >> 24) & 0xFF}.{(nip >> 16) & 0xFF}.{(nip >> 8) & 0xFF}.{nip & 0xFF}"
    display_name = f"[{index}] GigE: {user_name} {model_name} ({serial})"

    return DeviceInfo(
        index=index,
        device_type="GigE",
        user_name=user_name,
        model_name=model_name,
        serial=serial,
        display_name=display_name,
    )


def _parse_usb_device(index: int, mvcc: MV_CC_DEVICE_INFO) -> DeviceInfo:
    """Парсинг информации USB-устройства."""
    user_name = ""
    model_name = ""

    try:
        user_name = ctypes.cast(
            mvcc.SpecialInfo.stUsb3VInfo.chUserDefinedName,
            ctypes.c_char_p,
        ).value.decode("gbk", errors="replace")
    except Exception:
        pass

    try:
        model_name = ctypes.cast(
            mvcc.SpecialInfo.stUsb3VInfo.chModelName,
            ctypes.c_char_p,
        ).value.decode("gbk", errors="replace")
    except Exception:
        pass

    serial = "".join(chr(b) for b in mvcc.SpecialInfo.stUsb3VInfo.chSerialNumber if b)
    display_name = f"[{index}] USB: {user_name} {model_name} ({serial})"

    return DeviceInfo(
        index=index,
        device_type="USB",
        user_name=user_name,
        model_name=model_name,
        serial=serial,
        display_name=display_name,
    )


def enum_devices() -> list[DeviceInfo]:
    """Перечислить доступные камеры GigE/USB.

    Returns
    -------
    list[DeviceInfo]
        Список найденных устройств. Пустой список, если SDK недоступен
        или камеры не найдены.
    """
    if not SDK_AVAILABLE:
        return []

    try:
        device_list = MV_CC_DEVICE_INFO_LIST()
        check_sdk_error(
            MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, device_list),
            "enum_devices",
        )

        if device_list.nDeviceNum == 0:
            return []

        devices: list[DeviceInfo] = []

        for i in range(device_list.nDeviceNum):
            mvcc = ctypes.cast(
                device_list.pDeviceInfo[i],
                POINTER(MV_CC_DEVICE_INFO),
            ).contents

            try:
                if mvcc.nTLayerType == MV_GIGE_DEVICE:
                    devices.append(_parse_gige_device(i, mvcc))
                elif mvcc.nTLayerType == MV_USB_DEVICE:
                    devices.append(_parse_usb_device(i, mvcc))
                else:
                    # Неизвестный тип устройства
                    devices.append(
                        DeviceInfo(
                            index=i,
                            device_type="Unknown",
                            user_name="",
                            model_name="",
                            serial="",
                            display_name=f"[{i}] Unknown",
                        )
                    )
            except Exception:
                # Битая запись — добавляем заглушку
                devices.append(
                    DeviceInfo(
                        index=i,
                        device_type="Unknown",
                        user_name="",
                        model_name="",
                        serial="",
                        display_name=f"[{i}] Unknown",
                    )
                )

        return devices

    except SdkError:
        return []
    except Exception:
        return []
