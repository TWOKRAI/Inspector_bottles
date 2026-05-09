# -*- coding: utf-8 -*-
"""ctypes-структуры Hikvision SDK -- только необходимые для работы."""
from __future__ import annotations

from ctypes import (
    Structure,
    Union,
    POINTER,
    c_ubyte,
    c_ushort,
    c_uint,
    c_int,
    c_int64,
    c_float,
    c_char,
    c_void_p,
)

from .constants import INFO_MAX_BUFFER_SIZE, MV_MAX_DEVICE_NUM


# ---------------------------------------------------------------------------
# Псевдоним для типа пикселя (enum хранится как c_int в SDK)
# ---------------------------------------------------------------------------
MvGvspPixelType = c_int
int64_t = c_int64


# =========================================================================
# Информация об устройствах
# =========================================================================

class MV_GIGE_DEVICE_INFO(Structure):
    """Информация о GigE-устройстве."""
    _fields_ = [
        ('nIpCfgOption', c_uint),                     # Опции IP-конфигурации
        ('nIpCfgCurrent', c_uint),                    # Текущая конфигурация IP
        ('nCurrentIp', c_uint),                       # Текущий IP-адрес
        ('nCurrentSubNetMask', c_uint),               # Текущая маска подсети
        ('nDefultGateWay', c_uint),                   # Шлюз по умолчанию
        ('chManufacturerName', c_ubyte * 32),          # Производитель
        ('chModelName', c_ubyte * 32),                 # Модель
        ('chDeviceVersion', c_ubyte * 32),             # Версия прошивки
        ('chManufacturerSpecificInfo', c_ubyte * 48),  # Доп. информация производителя
        ('chSerialNumber', c_ubyte * 16),              # Серийный номер
        ('chUserDefinedName', c_ubyte * 16),           # Пользовательское имя
        ('nNetExport', c_uint),                       # IP сетевого интерфейса
        ('nReserved', c_uint * 4),                    # Зарезервировано
    ]


class MV_USB3_DEVICE_INFO(Structure):
    """Информация о USB3 Vision устройстве."""
    _fields_ = [
        ('CrtlInEndPoint', c_ubyte),                            # Входной endpoint управления
        ('CrtlOutEndPoint', c_ubyte),                           # Выходной endpoint управления
        ('StreamEndPoint', c_ubyte),                            # Потоковый endpoint
        ('EventEndPoint', c_ubyte),                             # Endpoint событий
        ('idVendor', c_ushort),                                 # Vendor ID
        ('idProduct', c_ushort),                                # Product ID
        ('nDeviceNumber', c_uint),                              # Серийный номер устройства
        ('chDeviceGUID', c_ubyte * INFO_MAX_BUFFER_SIZE),       # GUID устройства
        ('chVendorName', c_ubyte * INFO_MAX_BUFFER_SIZE),       # Имя производителя
        ('chModelName', c_ubyte * INFO_MAX_BUFFER_SIZE),        # Имя модели
        ('chFamilyName', c_ubyte * INFO_MAX_BUFFER_SIZE),       # Семейство
        ('chDeviceVersion', c_ubyte * INFO_MAX_BUFFER_SIZE),    # Версия устройства
        ('chManufacturerName', c_ubyte * INFO_MAX_BUFFER_SIZE), # Производитель
        ('chSerialNumber', c_ubyte * INFO_MAX_BUFFER_SIZE),     # Серийный номер
        ('chUserDefinedName', c_ubyte * INFO_MAX_BUFFER_SIZE),  # Пользовательское имя
        ('nbcdUSB', c_uint),                                    # Поддерживаемый USB-протокол
        ('nDeviceAddress', c_uint),                             # Адрес устройства
        ('nReserved', c_uint * 2),                              # Зарезервировано
    ]


class _MV_CC_DEVICE_INFO_UNION(Union):
    """Union с информацией о конкретном типе устройства."""
    _fields_ = [
        ('stGigEInfo', MV_GIGE_DEVICE_INFO),   # GigE-информация
        ('stUsb3VInfo', MV_USB3_DEVICE_INFO),  # USB3-информация
    ]


class MV_CC_DEVICE_INFO(Structure):
    """Общая структура информации об устройстве."""
    _fields_ = [
        ('nMajorVer', c_ushort),                         # Основная версия спецификации
        ('nMinorVer', c_ushort),                         # Вторичная версия спецификации
        ('nMacAddrHigh', c_uint),                        # MAC-адрес (старшие байты)
        ('nMacAddrLow', c_uint),                         # MAC-адрес (младшие байты)
        ('nTLayerType', c_uint),                         # Тип транспортного уровня
        ('nReserved', c_uint * 4),                       # Зарезервировано
        ('SpecialInfo', _MV_CC_DEVICE_INFO_UNION),       # Специфичная информация
    ]


class MV_CC_DEVICE_INFO_LIST(Structure):
    """Список обнаруженных устройств (до 256)."""
    _fields_ = [
        ('nDeviceNum', c_uint),                                          # Количество устройств
        ('pDeviceInfo', POINTER(MV_CC_DEVICE_INFO) * MV_MAX_DEVICE_NUM), # Указатели на информацию
    ]


# =========================================================================
# Изображения / фреймы
# =========================================================================

class _MV_CHUNK_DATA_CONTENT(Structure):
    """Chunk-данные внутри фрейма."""
    _fields_ = [
        ('pChunkData', POINTER(c_ubyte)),  # Указатель на данные чанка
        ('nChunkID', c_uint),              # ID чанка
        ('nChunkLen', c_uint),             # Длина чанка
        ('nReserved', c_uint * 8),         # Зарезервировано
    ]


class _MV_FRAME_OUT_INFO_UNION(Union):
    """Union для unparsed chunk-данных."""
    _fields_ = [
        ('pUnparsedChunkContent', POINTER(_MV_CHUNK_DATA_CONTENT)),
        ('nAligning', int64_t),
    ]


class MV_FRAME_OUT_INFO(Structure):
    """Метаданные выходного кадра (MV_FRAME_OUT_INFO_EX в оригинале)."""
    _fields_ = [
        ('nWidth', c_ushort),                              # Ширина изображения
        ('nHeight', c_ushort),                             # Высота изображения
        ('enPixelType', MvGvspPixelType),                  # Формат пикселей
        ('nFrameNum', c_uint),                             # Номер кадра
        ('nDevTimeStampHigh', c_uint),                     # Временная метка (старшие 32 бита)
        ('nDevTimeStampLow', c_uint),                      # Временная метка (младшие 32 бита)
        ('nReserved0', c_uint),                            # Выравнивание 8 байт
        ('nHostTimeStamp', int64_t),                       # Временная метка хоста
        ('nFrameLen', c_uint),                             # Длина кадра в байтах
        # Водяные знаки (chunk)
        ('nSecondCount', c_uint),
        ('nCycleCount', c_uint),
        ('nCycleOffset', c_uint),
        ('fGain', c_float),                                # Усиление
        ('fExposureTime', c_float),                        # Время экспозиции
        ('nAverageBrightness', c_uint),                    # Средняя яркость
        # Баланс белого
        ('nRed', c_uint),
        ('nGreen', c_uint),
        ('nBlue', c_uint),
        ('nFrameCounter', c_uint),                         # Счётчик кадров
        ('nTriggerIndex', c_uint),                         # Индекс триггера
        # Вход/выход
        ('nInput', c_uint),
        ('nOutput', c_uint),
        # ROI
        ('nOffsetX', c_ushort),
        ('nOffsetY', c_ushort),
        ('nChunkWidth', c_ushort),
        ('nChunkHeight', c_ushort),
        ('nLostPacket', c_uint),                           # Потерянные пакеты в кадре
        ('nUnparsedChunkNum', c_uint),                     # Число неразобранных чанков
        ('UnparsedChunkList', _MV_FRAME_OUT_INFO_UNION),   # Список чанков
        ('nExtendWidth', c_uint),                          # Ширина (расширенная)
        ('nExtendHeight', c_uint),                         # Высота (расширенная)
        ('nReserved', c_uint * 34),                        # Зарезервировано
    ]


class MV_FRAME_OUT(Structure):
    """Выходной кадр: указатель на данные + метаданные."""
    _fields_ = [
        ('pBufAddr', POINTER(c_ubyte)),         # Указатель на буфер изображения
        ('stFrameInfo', MV_FRAME_OUT_INFO),     # Информация о кадре
        ('nRes', c_uint * 16),                  # Зарезервировано
    ]


# =========================================================================
# Значения параметров камеры
# =========================================================================

MV_MAX_XML_SYMBOLIC_NUM: int = 64   # Макс. число символов XML (для Enum)

class MVCC_FLOATVALUE(Structure):
    """Float-значение параметра камеры."""
    _fields_ = [
        ('fCurValue', c_float),    # Текущее значение
        ('fMax', c_float),         # Максимум
        ('fMin', c_float),         # Минимум
        ('nReserved', c_uint * 4), # Зарезервировано
    ]


class MVCC_INTVALUE(Structure):
    """Int-значение параметра камеры."""
    _fields_ = [
        ('nCurValue', c_uint),     # Текущее значение
        ('nMax', c_uint),          # Максимум
        ('nMin', c_uint),          # Минимум
        ('nInc', c_uint),          # Шаг
        ('nReserved', c_uint * 4), # Зарезервировано
    ]


class MVCC_ENUMVALUE(Structure):
    """Enum-значение параметра камеры."""
    _fields_ = [
        ('nCurValue', c_uint),                               # Текущее значение
        ('nSupportedNum', c_uint),                           # Количество поддерживаемых значений
        ('nSupportValue', c_uint * MV_MAX_XML_SYMBOLIC_NUM), # Список поддерживаемых значений
        ('nReserved', c_uint * 4),                           # Зарезервировано
    ]


class MVCC_STRINGVALUE(Structure):
    """String-значение параметра камеры."""
    _fields_ = [
        ('chCurValue', c_char * 256),  # Текущее значение
        ('nMaxLength', int64_t),       # Максимальная длина
        ('nReserved', c_uint * 2),     # Зарезервировано
    ]
