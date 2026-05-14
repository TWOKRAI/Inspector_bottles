# -*- coding: utf-8 -*-
"""Минимальный ctypes-wrapper для Hikvision MvCameraControl.dll.

Содержит только реально используемые методы (~15 из ~150).
При отсутствии DLL модуль не падает -- SDK_AVAILABLE = False.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import (
    byref,
    c_bool,
    c_float,
    c_uint,
    c_uint32,
    c_void_p,
    pointer,
)

from .structures import (
    MV_CC_DEVICE_INFO,
    MV_CC_DEVICE_INFO_LIST,
    MV_FRAME_OUT,
    MVCC_FLOATVALUE,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Загрузка DLL (graceful degradation)
# ---------------------------------------------------------------------------

_MvCamCtrldll = None
SDK_AVAILABLE: bool = False
"""True если DLL MvCameraControl.dll успешно загружена."""


def _load_sdk_library():
    """Загрузить нативную библиотеку Hikvision SDK.

    Поддерживаемые платформы:
        - Windows (x86/x64): MvCameraControl.dll
        - Linux (x86_64/aarch64): libMvCameraControl.so
          Включая NVIDIA Jetson (aarch64) и Raspberry Pi (aarch64).

    MVS SDK для Linux: https://www.hikrobotics.com/en/machinevision/service/download
    Установка: sudo dpkg -i MVS-*.deb → библиотека в /opt/MVS/lib/
    """
    if sys.platform == "win32":
        dll_name = "MvCameraControl.dll"
        try:
            if "winmode" in ctypes.WinDLL.__init__.__code__.co_varnames:
                lib = ctypes.WinDLL(dll_name, winmode=0)
            else:
                lib = ctypes.WinDLL(dll_name)
            logger.info("Hikvision SDK загружена: %s", dll_name)
            return lib
        except OSError as exc:
            logger.warning("Hikvision SDK не найдена (%s): %s", dll_name, exc)
            return None

    elif sys.platform.startswith("linux"):
        # Linux: MVS SDK ставит .so в /opt/MVS/lib/64/ или /opt/MVS/lib/aarch64/
        so_name = "libMvCameraControl.so"
        search_paths = [
            so_name,  # уже в LD_LIBRARY_PATH
            "/opt/MVS/lib/64/libMvCameraControl.so",  # x86_64 стандартный путь
            "/opt/MVS/lib/aarch64/libMvCameraControl.so",  # Jetson / RPi (ARM64)
            "/opt/MVS/lib/32/libMvCameraControl.so",  # x86 32-bit (редко)
        ]
        for path in search_paths:
            try:
                lib = ctypes.CDLL(path)
                logger.info("Hikvision SDK загружена: %s", path)
                return lib
            except OSError:
                continue
        logger.warning(
            "Hikvision SDK не найдена. Проверьте установку MVS SDK: "
            "sudo dpkg -i MVS-*.deb, затем добавьте /opt/MVS/lib/ в LD_LIBRARY_PATH"
        )
        return None

    else:
        logger.info("Платформа %s — Hikvision SDK не поддерживается.", sys.platform)
        return None


_MvCamCtrldll = _load_sdk_library()
SDK_AVAILABLE: bool = _MvCamCtrldll is not None
"""True если библиотека Hikvision SDK успешно загружена."""


def _require_dll():
    """Вернуть загруженную библиотеку SDK или выбросить RuntimeError."""
    if _MvCamCtrldll is None:
        if sys.platform == "win32":
            hint = "Убедитесь что MvCameraControl.dll доступна в PATH."
        else:
            hint = "Установите MVS SDK: sudo dpkg -i MVS-*.deb, затем добавьте /opt/MVS/lib/ в LD_LIBRARY_PATH."
        raise RuntimeError(f"Hikvision SDK не загружена. {hint}")
    return _MvCamCtrldll


# ---------------------------------------------------------------------------
# Класс-обёртка
# ---------------------------------------------------------------------------


class MvCamera:
    """Минимальный Python-wrapper над Hikvision MvCameraControl.dll.

    Содержит только методы, реально используемые в проекте.
    Сигнатуры полностью повторяют оригинальный SDK.
    """

    def __init__(self) -> None:
        self._handle = c_void_p()  # handle текущего устройства
        self.handle = pointer(self._handle)

    # === Статические методы ================================================

    @staticmethod
    def MV_CC_GetSDKVersion() -> int:
        """Получить версию SDK.

        Returns:
            Номер версии SDK (unsigned int).
        """
        dll = _require_dll()
        dll.MV_CC_GetSDKVersion.restype = c_uint
        return dll.MV_CC_GetSDKVersion()

    @staticmethod
    def MV_CC_EnumDevices(
        nTLayerType: int,
        stDevList: MV_CC_DEVICE_INFO_LIST,
    ) -> int:
        """Перечислить доступные устройства.

        Args:
            nTLayerType: битовая маска типов транспорта (MV_GIGE_DEVICE | MV_USB_DEVICE).
            stDevList: структура для заполнения списком устройств.

        Returns:
            Код возврата SDK (0 = MV_OK).
        """
        dll = _require_dll()
        dll.MV_CC_EnumDevices.argtype = (c_uint, c_void_p)
        dll.MV_CC_EnumDevices.restype = c_uint
        return dll.MV_CC_EnumDevices(c_uint(nTLayerType), byref(stDevList))

    # === Управление handle =================================================

    def MV_CC_CreateHandle(self, stDevInfo: MV_CC_DEVICE_INFO) -> int:
        """Создать handle устройства.

        Args:
            stDevInfo: информация об устройстве из результатов перечисления.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        # Сначала уничтожаем предыдущий handle (как в оригинале)
        dll.MV_CC_DestroyHandle.argtype = c_void_p
        dll.MV_CC_DestroyHandle.restype = c_uint
        dll.MV_CC_DestroyHandle(self.handle)

        dll.MV_CC_CreateHandle.argtype = (c_void_p, c_void_p)
        dll.MV_CC_CreateHandle.restype = c_uint
        return dll.MV_CC_CreateHandle(byref(self.handle), byref(stDevInfo))

    def MV_CC_DestroyHandle(self) -> int:
        """Уничтожить handle устройства.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_DestroyHandle.argtype = c_void_p
        dll.MV_CC_DestroyHandle.restype = c_uint
        return dll.MV_CC_DestroyHandle(self.handle)

    # === Открытие / закрытие ===============================================

    def MV_CC_OpenDevice(
        self,
        nAccessMode: int = 1,
        nSwitchoverKey: int = 0,
    ) -> int:
        """Открыть устройство.

        Args:
            nAccessMode: режим доступа (по умолчанию MV_ACCESS_Exclusive = 1).
            nSwitchoverKey: ключ переключения (по умолчанию 0).

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_OpenDevice.argtype = (c_void_p, c_uint32, ctypes.c_uint16)
        dll.MV_CC_OpenDevice.restype = c_uint
        return dll.MV_CC_OpenDevice(self.handle, nAccessMode, nSwitchoverKey)

    def MV_CC_CloseDevice(self) -> int:
        """Закрыть устройство.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_CloseDevice.argtype = c_void_p
        dll.MV_CC_CloseDevice.restype = c_uint
        return dll.MV_CC_CloseDevice(self.handle)

    # === Захват потока =====================================================

    def MV_CC_StartGrabbing(self) -> int:
        """Начать захват изображений.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_StartGrabbing.argtype = c_void_p
        dll.MV_CC_StartGrabbing.restype = c_uint
        return dll.MV_CC_StartGrabbing(self.handle)

    def MV_CC_StopGrabbing(self) -> int:
        """Остановить захват изображений.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_StopGrabbing.argtype = c_void_p
        dll.MV_CC_StopGrabbing.restype = c_uint
        return dll.MV_CC_StopGrabbing(self.handle)

    # === Получение изображений =============================================

    def MV_CC_GetImageBuffer(self, stFrame: MV_FRAME_OUT, nMsec: int) -> int:
        """Получить кадр из внутреннего буфера SDK.

        Args:
            stFrame: структура для заполнения данными кадра.
            nMsec: таймаут в миллисекундах.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_GetImageBuffer.argtype = (c_void_p, c_void_p, c_uint)
        dll.MV_CC_GetImageBuffer.restype = c_uint
        return dll.MV_CC_GetImageBuffer(self.handle, byref(stFrame), nMsec)

    def MV_CC_FreeImageBuffer(self, stFrame: MV_FRAME_OUT) -> int:
        """Освободить буфер кадра, полученный через MV_CC_GetImageBuffer.

        Args:
            stFrame: структура кадра для освобождения.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_FreeImageBuffer.argtype = (c_void_p, c_void_p)
        dll.MV_CC_FreeImageBuffer.restype = c_uint
        return dll.MV_CC_FreeImageBuffer(self.handle, byref(stFrame))

    # === Установка параметров ==============================================

    def MV_CC_SetEnumValue(self, strKey: str, nValue: int) -> int:
        """Установить Enum-параметр камеры.

        Args:
            strKey: имя параметра (например ``"TriggerMode"``).
            nValue: числовое значение.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_SetEnumValue.argtype = (c_void_p, c_void_p, c_uint32)
        dll.MV_CC_SetEnumValue.restype = c_uint
        return dll.MV_CC_SetEnumValue(
            self.handle,
            strKey.encode("ascii"),
            c_uint32(nValue),
        )

    def MV_CC_SetBoolValue(self, strKey: str, bValue: bool) -> int:
        """Установить Boolean-параметр камеры.

        Args:
            strKey: имя параметра.
            bValue: логическое значение.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_SetBoolValue.argtype = (c_void_p, c_void_p, c_bool)
        dll.MV_CC_SetBoolValue.restype = c_uint
        return dll.MV_CC_SetBoolValue(
            self.handle,
            strKey.encode("ascii"),
            bValue,
        )

    def MV_CC_SetFloatValue(self, strKey: str, fValue: float) -> int:
        """Установить Float-параметр камеры.

        Args:
            strKey: имя параметра (например ``"ExposureTime"``).
            fValue: значение с плавающей точкой.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_SetFloatValue.argtype = (c_void_p, c_void_p, c_float)
        dll.MV_CC_SetFloatValue.restype = c_uint
        return dll.MV_CC_SetFloatValue(
            self.handle,
            strKey.encode("ascii"),
            c_float(fValue),
        )

    def MV_CC_SetIntValue(self, strKey: str, nValue: int) -> int:
        """Установить Int-параметр камеры.

        Args:
            strKey: имя параметра.
            nValue: целочисленное значение.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_SetIntValue.argtype = (c_void_p, c_void_p, c_uint32)
        dll.MV_CC_SetIntValue.restype = c_uint
        return dll.MV_CC_SetIntValue(
            self.handle,
            strKey.encode("ascii"),
            c_uint32(nValue),
        )

    # === Получение параметров ==============================================

    def MV_CC_GetFloatValue(
        self,
        strKey: str,
        stFloatValue: MVCC_FLOATVALUE,
    ) -> int:
        """Получить Float-параметр камеры.

        Args:
            strKey: имя параметра.
            stFloatValue: структура для заполнения значением.

        Returns:
            Код возврата SDK.
        """
        dll = _require_dll()
        dll.MV_CC_GetFloatValue.argtype = (c_void_p, c_void_p, c_void_p)
        dll.MV_CC_GetFloatValue.restype = c_uint
        return dll.MV_CC_GetFloatValue(
            self.handle,
            strKey.encode("ascii"),
            byref(stFloatValue),
        )

    def MV_CC_GetOptimalPacketSize(self) -> int:
        """Получить оптимальный размер сетевого пакета (только GigE).

        Returns:
            Оптимальный размер пакета (int) или код ошибки.
        """
        dll = _require_dll()
        dll.MV_CC_GetOptimalPacketSize.argtype = (c_void_p,)
        dll.MV_CC_GetOptimalPacketSize.restype = c_uint
        return dll.MV_CC_GetOptimalPacketSize(self.handle)
