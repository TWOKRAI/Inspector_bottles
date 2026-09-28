# -*- coding: utf-8 -*-
"""Зонд GigE Vision discovery для считывателя ID3000 (Ф0 плана qr-code-reader).

Печатает всё, что устройство отдаёт в ответ на broadcast: версию прошивки, IP,
маску, режим IP-конфигурации. Ни открытия устройства, ни MvCodeReader SDK,
ни IDMVS не требуется — достаточно линка и питания.

Запуск из корня репозитория:
    .venv/Scripts/python.exe Services/code_reader/tools/id3000_discover.py
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

# Запуск прямым путём кладёт в sys.path каталог скрипта, а не корень репозитория —
# тот же приём, что в scripts/robot_ref_against_sim.py.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Значения nIpCfgCurrent по GigE Vision (битовая маска)
IP_CFG = {0x1: "LLA", 0x2: "DHCP", 0x4: "StaticIP"}


def _text(buf) -> str:
    """Си-строка из массива c_ubyte."""
    return bytes(buf).split(b"\x00")[0].decode("gbk", errors="replace")


def _ip(value: int) -> str:
    return ".".join(str((value >> shift) & 0xFF) for shift in (24, 16, 8, 0))


def _cfg(mask: int) -> str:
    names = [name for bit, name in IP_CFG.items() if mask & bit]
    return "+".join(names) if names else "?"


def main() -> int:
    # Импорт внутри функции: до него sys.path выше должен успеть подняться
    # к корню репозитория. Тот же приём, что в scripts/robot_ref_against_sim.py.
    from Services.hikvision_camera.sdk.bindings import SDK_AVAILABLE, MvCamera
    from Services.hikvision_camera.sdk.constants import MV_GIGE_DEVICE, MV_USB_DEVICE
    from Services.hikvision_camera.sdk.structures import (
        MV_CC_DEVICE_INFO,
        MV_CC_DEVICE_INFO_LIST,
    )

    print(f"SDK_AVAILABLE={SDK_AVAILABLE}")
    if not SDK_AVAILABLE:
        print("MVS SDK не загрузился — проверь установку MVS")
        return 2

    devices = MV_CC_DEVICE_INFO_LIST()
    rc = MvCamera.MV_CC_EnumDevices(MV_GIGE_DEVICE | MV_USB_DEVICE, devices)
    print(f"MV_CC_EnumDevices rc=0x{rc & 0xFFFFFFFF:08X}  найдено={devices.nDeviceNum}")
    if devices.nDeviceNum == 0:
        print("Пусто. Проверь: линк на сетевой карте, питание 24 В, брандмауэр Windows.")
        return 1

    for index in range(devices.nDeviceNum):
        info = ctypes.cast(devices.pDeviceInfo[index], ctypes.POINTER(MV_CC_DEVICE_INFO)).contents
        print(f"\n--- устройство [{index}] TLayerType=0x{info.nTLayerType:X} ---")
        if info.nTLayerType == MV_GIGE_DEVICE:
            gige = info.SpecialInfo.stGigEInfo
            print(f"  Производитель    : {_text(gige.chManufacturerName)}")
            print(f"  Модель           : {_text(gige.chModelName)}")
            print(f"  ВЕРСИЯ ПРОШИВКИ  : {_text(gige.chDeviceVersion)}")
            print(f"  Серийный номер   : {_text(gige.chSerialNumber)}")
            print(f"  Пользоват. имя   : {_text(gige.chUserDefinedName)}")
            print(f"  Доп. инфо вендора: {_text(gige.chManufacturerSpecificInfo)}")
            print(f"  IP               : {_ip(gige.nCurrentIp)}")
            print(f"  Маска / шлюз     : {_ip(gige.nCurrentSubNetMask)} / {_ip(gige.nDefultGateWay)}")
            print(f"  Сетевая карта ПК : {_ip(gige.nNetExport)}")
            print(f"  Режим IP         : текущий {_cfg(gige.nIpCfgCurrent)}  (поддерживает {_cfg(gige.nIpCfgOption)})")
        else:
            usb = info.SpecialInfo.stUsb3VInfo
            print(f"  Модель         : {_text(usb.chModelName)}")
            print(f"  ВЕРСИЯ ПРОШИВКИ: {_text(usb.chDeviceVersion)}")
            print(f"  Серийный номер : {_text(usb.chSerialNumber)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
