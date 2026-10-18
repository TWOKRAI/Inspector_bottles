# -*- coding: utf-8 -*-
"""Минимальный ctypes-wrapper для Hikvision MvCameraControl.dll.

Содержит только реально используемые методы (~15 из ~150).
При отсутствии DLL модуль не падает -- SDK_AVAILABLE = False.
"""

from __future__ import annotations

import ctypes

from multiprocess_framework.modules.logger_module import get_std_logger
import sys
from ctypes import (
    byref,
    c_bool,
    c_char_p,
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
    MVCC_ENUMENTRY,
    MVCC_ENUMVALUE,
    MVCC_FLOATVALUE,
    MVCC_INTVALUE,
    MVCC_INTVALUE_EX,
    MVCC_STRINGVALUE,
)

logger = get_std_logger(__name__)

# Прототип колбэка исключений: MvCameraControl.h:1362 --
# void(__stdcall* cbException)(unsigned int nMsgType, void* pUser).
# WINFUNCTYPE есть только на Windows; на Linux SDK вызывает cdecl.
EXCEPTION_CALLBACK = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(None, c_uint, c_void_p)
"""Тип колбэка для ``MvCamera.MV_CC_RegisterExceptionCallBack``."""


def _as_pointer_arg(obj):
    """Указатель на выходной параметр: ``byref(obj)``; готовый ``byref`` проходит как есть."""
    if isinstance(obj, type(byref(c_uint()))):
        return obj
    return byref(obj)


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
        # Ссылка на CFUNCTYPE-колбэк: без неё GC освободит thunk, SDK вызовет мусор.
        self._exception_cb = None

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

    # === Получение параметров: целые, enum, bool, string ===================

    def MV_CC_GetIntValue(
        self,
        strKey: str,
        stIntValue: MVCC_INTVALUE,
    ) -> int:
        """Получить Int-параметр камеры (32-битная структура).

        Функция экспортируется DLL, но её прототипа нет в MvCameraControl.h
        (SDK 0x04020003); раскладка -- по существующей ``MVCC_INTVALUE``.
        Для значений выше 32 бит -- ``MV_CC_GetIntValueEx``.
        """
        dll = _require_dll()
        dll.MV_CC_GetIntValue.argtypes = (c_void_p, c_char_p, c_void_p)
        dll.MV_CC_GetIntValue.restype = c_uint
        return dll.MV_CC_GetIntValue(
            self.handle,
            strKey.encode("ascii"),
            _as_pointer_arg(stIntValue),
        )

    def MV_CC_GetIntValueEx(
        self,
        strKey: str,
        stIntValue: MVCC_INTVALUE_EX,
    ) -> int:
        """Получить Int-параметр камеры (int64-структура, MvCameraControl.h:812)."""
        dll = _require_dll()
        dll.MV_CC_GetIntValueEx.argtypes = (c_void_p, c_char_p, c_void_p)
        dll.MV_CC_GetIntValueEx.restype = c_uint
        return dll.MV_CC_GetIntValueEx(
            self.handle,
            strKey.encode("ascii"),
            _as_pointer_arg(stIntValue),
        )

    def MV_CC_GetEnumValue(
        self,
        strKey: str,
        stEnumValue: MVCC_ENUMVALUE,
    ) -> int:
        """Получить Enum-параметр камеры (MvCameraControl.h:854)."""
        dll = _require_dll()
        dll.MV_CC_GetEnumValue.argtypes = (c_void_p, c_char_p, c_void_p)
        dll.MV_CC_GetEnumValue.restype = c_uint
        return dll.MV_CC_GetEnumValue(
            self.handle,
            strKey.encode("ascii"),
            _as_pointer_arg(stEnumValue),
        )

    def MV_CC_GetBoolValue(self, strKey: str, pbValue) -> int:
        """Получить Boolean-параметр камеры (MvCameraControl.h:985).

        Args:
            pbValue: ``c_bool()`` для заполнения (или готовый ``byref(c_bool())``)."""
        dll = _require_dll()
        dll.MV_CC_GetBoolValue.argtypes = (c_void_p, c_char_p, c_void_p)
        dll.MV_CC_GetBoolValue.restype = c_uint
        return dll.MV_CC_GetBoolValue(
            self.handle,
            strKey.encode("ascii"),
            _as_pointer_arg(pbValue),
        )

    def MV_CC_GetStringValue(
        self,
        strKey: str,
        stStringValue: MVCC_STRINGVALUE,
    ) -> int:
        """Получить String-параметр камеры (MvCameraControl.h:1029)."""
        dll = _require_dll()
        dll.MV_CC_GetStringValue.argtypes = (c_void_p, c_char_p, c_void_p)
        dll.MV_CC_GetStringValue.restype = c_uint
        return dll.MV_CC_GetStringValue(
            self.handle,
            strKey.encode("ascii"),
            _as_pointer_arg(stStringValue),
        )

    def MV_CC_GetEnumEntrySymbolic(
        self,
        strKey: str,
        stEnumEntry: MVCC_ENUMENTRY,
    ) -> int:
        """Получить символьное имя значения enum-узла (MvCameraControl.h:897).

        ``stEnumEntry.nValue`` -- вход, ``stEnumEntry.chSymbolic`` -- выход.
        """
        dll = _require_dll()
        dll.MV_CC_GetEnumEntrySymbolic.argtypes = (c_void_p, c_char_p, c_void_p)
        dll.MV_CC_GetEnumEntrySymbolic.restype = c_uint
        return dll.MV_CC_GetEnumEntrySymbolic(
            self.handle,
            strKey.encode("ascii"),
            _as_pointer_arg(stEnumEntry),
        )

    # === Установка параметров (строка / команда) ===========================

    def MV_CC_SetEnumValueByString(self, strKey: str, strValue: str) -> int:
        """Установить Enum-параметр по символьному значению (MvCameraControl.h:919).

        Args:
            strKey: имя параметра (например ``"TriggerSource"``).
            strValue: символьное значение (например ``"Line0"``).
        """
        dll = _require_dll()
        dll.MV_CC_SetEnumValueByString.argtypes = (c_void_p, c_char_p, c_char_p)
        dll.MV_CC_SetEnumValueByString.restype = c_uint
        return dll.MV_CC_SetEnumValueByString(
            self.handle,
            strKey.encode("ascii"),
            strValue.encode("ascii"),
        )

    def MV_CC_SetCommandValue(self, strKey: str) -> int:
        """Выполнить команду-узел (например ``"TriggerSoftware"``, MvCameraControl.h:1071)."""
        dll = _require_dll()
        dll.MV_CC_SetCommandValue.argtypes = (c_void_p, c_char_p)
        dll.MV_CC_SetCommandValue.restype = c_uint
        return dll.MV_CC_SetCommandValue(
            self.handle,
            strKey.encode("ascii"),
        )

    # === Узлы XML ===========================================================

    def MV_XML_GetNodeAccessMode(self, strName: str, penAccessMode) -> int:
        """Режим доступа к узлу (MvCameraControl.h:1170).

        Args:
            penAccessMode: ``c_int()`` (или готовый ``byref``); значения -- ``AM_*`` из structures."""
        dll = _require_dll()
        dll.MV_XML_GetNodeAccessMode.argtypes = (c_void_p, c_char_p, c_void_p)
        dll.MV_XML_GetNodeAccessMode.restype = c_uint
        return dll.MV_XML_GetNodeAccessMode(
            self.handle,
            strName.encode("ascii"),
            _as_pointer_arg(penAccessMode),
        )

    def MV_XML_GetNodeInterfaceType(self, strName: str, penInterfaceType) -> int:
        """Тип интерфейса узла (MvCameraControl.h:1189).

        Args:
            penInterfaceType: ``c_int()`` (или готовый ``byref``); значения -- ``IFT_*`` из structures."""
        dll = _require_dll()
        dll.MV_XML_GetNodeInterfaceType.argtypes = (c_void_p, c_char_p, c_void_p)
        dll.MV_XML_GetNodeInterfaceType.restype = c_uint
        return dll.MV_XML_GetNodeInterfaceType(
            self.handle,
            strName.encode("ascii"),
            _as_pointer_arg(penInterfaceType),
        )

    # === Колбэк исключений ==================================================

    def MV_CC_RegisterExceptionCallBack(self, cbException, pUser=None) -> int:
        """Зарегистрировать колбэк исключений устройства (MvCameraControl.h:1362).

        Args:
            cbException: объект ``EXCEPTION_CALLBACK`` (``None`` -- снять колбэк).
            pUser: пользовательский указатель (``c_void_p`` или ``None``).

        Ссылка на колбэк хранится в ``self._exception_cb``: иначе GC освободит
        ctypes-thunk, и SDK вызовет его -- падение процесса.
        """
        dll = _require_dll()
        dll.MV_CC_RegisterExceptionCallBack.argtypes = (c_void_p, EXCEPTION_CALLBACK, c_void_p)
        dll.MV_CC_RegisterExceptionCallBack.restype = c_uint
        self._exception_cb = cbException  # до вызова: колбэк может сработать сразу
        return dll.MV_CC_RegisterExceptionCallBack(self.handle, cbException, pUser)

    def MV_CC_GetOptimalPacketSize(self) -> int:
        """Получить оптимальный размер сетевого пакета (только GigE).

        Returns:
            Оптимальный размер пакета (int) или код ошибки.
        """
        dll = _require_dll()
        dll.MV_CC_GetOptimalPacketSize.argtype = (c_void_p,)
        dll.MV_CC_GetOptimalPacketSize.restype = c_uint
        return dll.MV_CC_GetOptimalPacketSize(self.handle)
