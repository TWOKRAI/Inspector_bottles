# -*- coding: utf-8 -*-
"""Коды ошибок Hikvision SDK и утилиты обработки ошибок."""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Коды ошибок SDK (полный набор из MvErrorDefine_const)
# ---------------------------------------------------------------------------

MV_OK: int = 0x00000000  # Успех

# Общие ошибки (0x80000000 - 0x800000FF)
MV_E_HANDLE: int = 0x80000000               # Неверный или отсутствующий handle
MV_E_SUPPORT: int = 0x80000001              # Функция не поддерживается
MV_E_BUFOVER: int = 0x80000002              # Переполнение буфера
MV_E_CALLORDER: int = 0x80000003            # Неверный порядок вызова функций
MV_E_PARAMETER: int = 0x80000004            # Неверный параметр
MV_E_RESOURCE: int = 0x80000006             # Ошибка выделения ресурсов
MV_E_NODATA: int = 0x80000007              # Нет данных
MV_E_PRECONDITION: int = 0x80000008         # Не выполнены предусловия
MV_E_VERSION: int = 0x80000009              # Несоответствие версий
MV_E_NOENOUGH_BUF: int = 0x8000000A        # Недостаточно памяти
MV_E_ABNORMAL_IMAGE: int = 0x8000000B      # Аномальное изображение (возможна потеря пакетов)
MV_E_LOAD_LIBRARY: int = 0x8000000C        # Ошибка загрузки DLL
MV_E_NOOUTBUF: int = 0x8000000D            # Нет доступного выходного буфера
MV_E_UNKNOW: int = 0x800000FF              # Неизвестная ошибка

# Ошибки GenICam (0x80000100 - 0x800001FF)
MV_E_GC_GENERIC: int = 0x80000100          # Общая ошибка GenICam
MV_E_GC_ARGUMENT: int = 0x80000101         # Недопустимые параметры
MV_E_GC_RANGE: int = 0x80000102            # Значение вне диапазона
MV_E_GC_PROPERTY: int = 0x80000103         # Ошибка свойства
MV_E_GC_RUNTIME: int = 0x80000104          # Ошибка среды выполнения
MV_E_GC_LOGICAL: int = 0x80000105          # Логическая ошибка
MV_E_GC_ACCESS: int = 0x80000106           # Ошибка условий доступа к узлу
MV_E_GC_TIMEOUT: int = 0x80000107          # Таймаут
MV_E_GC_DYNAMICCAST: int = 0x80000108      # Ошибка преобразования типов
MV_E_GC_UNKNOW: int = 0x800001FF           # Неизвестная ошибка GenICam

# Ошибки GigE (0x80000200 - 0x800002FF)
MV_E_NOT_IMPLEMENTED: int = 0x80000200     # Команда не поддерживается устройством
MV_E_INVALID_ADDRESS: int = 0x80000201     # Целевой адрес не существует
MV_E_WRITE_PROTECT: int = 0x80000202       # Адрес защищён от записи
MV_E_ACCESS_DENIED: int = 0x80000203       # Нет прав доступа к устройству
MV_E_BUSY: int = 0x80000204               # Устройство занято или сеть отключена
MV_E_PACKET: int = 0x80000205             # Ошибка сетевого пакета
MV_E_NETER: int = 0x80000206              # Сетевая ошибка
MV_E_IP_CONFLICT: int = 0x80000221        # Конфликт IP-адресов

# Ошибки USB (0x80000300 - 0x800003FF)
MV_E_USB_READ: int = 0x80000300           # Ошибка чтения USB
MV_E_USB_WRITE: int = 0x80000301          # Ошибка записи USB
MV_E_USB_DEVICE: int = 0x80000302         # Исключение устройства USB
MV_E_USB_GENICAM: int = 0x80000303        # Ошибка GenICam (USB)
MV_E_USB_BANDWIDTH: int = 0x80000304      # Недостаточная пропускная способность USB
MV_E_USB_DRIVER: int = 0x80000305         # Несоответствие драйвера или драйвер не установлен
MV_E_USB_UNKNOW: int = 0x800003FF         # Неизвестная ошибка USB

# Ошибки обновления (0x80000400 - 0x800004FF)
MV_E_UPG_FILE_MISMATCH: int = 0x80000400       # Несоответствие прошивки
MV_E_UPG_LANGUSGE_MISMATCH: int = 0x80000401   # Несоответствие языка прошивки
MV_E_UPG_CONFLICT: int = 0x80000402             # Конфликт обновления (повторный запрос)
MV_E_UPG_INNER_ERR: int = 0x80000403            # Внутренняя ошибка устройства при обновлении
MV_E_UPG_UNKNOW: int = 0x800004FF               # Неизвестная ошибка обновления


# ---------------------------------------------------------------------------
# Маппинг код -> описание (на русском)
# ---------------------------------------------------------------------------

_ERROR_DESCRIPTIONS: dict[int, str] = {
    MV_OK:                      "Успех",
    MV_E_HANDLE:                "Неверный или отсутствующий handle",
    MV_E_SUPPORT:               "Функция не поддерживается",
    MV_E_BUFOVER:               "Переполнение буфера",
    MV_E_CALLORDER:             "Неверный порядок вызова функций",
    MV_E_PARAMETER:             "Неверный параметр",
    MV_E_RESOURCE:              "Ошибка выделения ресурсов",
    MV_E_NODATA:                "Нет данных",
    MV_E_PRECONDITION:          "Не выполнены предусловия или изменилась среда выполнения",
    MV_E_VERSION:               "Несоответствие версий",
    MV_E_NOENOUGH_BUF:          "Недостаточно памяти (переданный буфер слишком мал)",
    MV_E_ABNORMAL_IMAGE:        "Аномальное изображение (возможна потеря пакетов)",
    MV_E_LOAD_LIBRARY:          "Ошибка загрузки DLL",
    MV_E_NOOUTBUF:              "Нет доступного выходного буфера",
    MV_E_UNKNOW:                "Неизвестная ошибка",
    MV_E_GC_GENERIC:            "Общая ошибка GenICam",
    MV_E_GC_ARGUMENT:           "Недопустимые параметры GenICam",
    MV_E_GC_RANGE:              "Значение вне допустимого диапазона",
    MV_E_GC_PROPERTY:           "Ошибка свойства GenICam",
    MV_E_GC_RUNTIME:            "Ошибка среды выполнения GenICam",
    MV_E_GC_LOGICAL:            "Логическая ошибка GenICam",
    MV_E_GC_ACCESS:             "Ошибка условий доступа к узлу GenICam",
    MV_E_GC_TIMEOUT:            "Таймаут GenICam",
    MV_E_GC_DYNAMICCAST:        "Ошибка преобразования типов GenICam",
    MV_E_GC_UNKNOW:             "Неизвестная ошибка GenICam",
    MV_E_NOT_IMPLEMENTED:       "Команда не поддерживается устройством",
    MV_E_INVALID_ADDRESS:       "Целевой адрес не существует",
    MV_E_WRITE_PROTECT:         "Адрес защищён от записи",
    MV_E_ACCESS_DENIED:         "Нет прав доступа к устройству",
    MV_E_BUSY:                  "Устройство занято или сеть отключена",
    MV_E_PACKET:                "Ошибка сетевого пакета",
    MV_E_NETER:                 "Сетевая ошибка",
    MV_E_IP_CONFLICT:           "Конфликт IP-адресов устройства",
    MV_E_USB_READ:              "Ошибка чтения USB",
    MV_E_USB_WRITE:             "Ошибка записи USB",
    MV_E_USB_DEVICE:            "Исключение USB-устройства",
    MV_E_USB_GENICAM:           "Ошибка GenICam (USB)",
    MV_E_USB_BANDWIDTH:         "Недостаточная пропускная способность USB",
    MV_E_USB_DRIVER:            "Несоответствие драйвера или драйвер не установлен",
    MV_E_USB_UNKNOW:            "Неизвестная ошибка USB",
    MV_E_UPG_FILE_MISMATCH:     "Несоответствие файла прошивки",
    MV_E_UPG_LANGUSGE_MISMATCH: "Несоответствие языка прошивки",
    MV_E_UPG_CONFLICT:          "Конфликт обновления (повторный запрос при обновлении)",
    MV_E_UPG_INNER_ERR:         "Внутренняя ошибка устройства при обновлении",
    MV_E_UPG_UNKNOW:            "Неизвестная ошибка обновления",
}


# ---------------------------------------------------------------------------
# Публичные утилиты
# ---------------------------------------------------------------------------

class SdkError(Exception):
    """Исключение, выбрасываемое при ошибке вызова Hikvision SDK.

    Attributes:
        code: числовой код ошибки SDK.
        operation: название операции, при которой произошла ошибка.
        description: человекочитаемое описание ошибки (русский).
    """

    def __init__(self, code: int, operation: str) -> None:
        self.code = code
        self.operation = operation
        self.description = error_description(code)
        super().__init__(
            f"[SDK 0x{code:08X}] {operation}: {self.description}"
        )


def error_description(code: int) -> str:
    """Вернуть человекочитаемое описание ошибки по коду.

    Args:
        code: числовой код ошибки SDK.

    Returns:
        Описание на русском языке. Если код неизвестен --
        строка вида ``"Неизвестный код ошибки: 0x..."``
    """
    return _ERROR_DESCRIPTIONS.get(
        code,
        f"Неизвестный код ошибки: 0x{code:08X}",
    )


def check_sdk_error(ret: int, operation: str) -> None:
    """Проверить код возврата SDK и выбросить SdkError при ошибке.

    Args:
        ret: код возврата вызова SDK.
        operation: название операции (для диагностики).

    Raises:
        SdkError: если ``ret != MV_OK``.
    """
    if ret != MV_OK:
        raise SdkError(ret, operation)
