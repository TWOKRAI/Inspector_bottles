# -*- coding: utf-8 -*-
"""ctypes-структуры MvCodeReader SDK (``MvCodeReaderParams.h``, V1.5.3).

Имена полей — ровно как в заголовке: ctypes молча создаёт Python-атрибут при
присваивании несуществующему имени, поэтому опечатка в имени = тихая потеря данных.
Раскладка сверена с живым прибором (зонд лидера, 2026-09-29: 5 кадров, ``nLen``
совпал с длиной ``chCode`` на каждом коде) и с ручным расчётом смещений MSVC x64
в ``tests/test_sdk_layer.py``. C ``bool`` — 1 байт (``c_bool``), enum — 4 байта.
"""

from __future__ import annotations

import ctypes as C

# Транспортный слой для EnumDevices.
GIGE_DEVICE = 0x00000001
# Форматы кадра (enum MvCodeReaderGvspPixelType).
PIXEL_MONO8 = 0x01080001
PIXEL_JPEG = 0x80180001
# «Код есть, не читается» — nBarType записи NoRead. Значение СНЯТО с прибора
# (кадр 4 зонда, 2026-09-29), в заголовке V1.5.3 символом не описано.
BAR_TYPE_NOREAD = 1001

INFO_MAX_BUFFER_SIZE = 64
MAX_DEVICE_NUM = 256
MAX_BCR_CODE_LEN_EX = 4096
MAX_BCR_COUNT_EX = 300


class GIGE_DEVICE_INFO(C.Structure):
    """MV_CODEREADER_GIGE_DEVICE_INFO — 216 байт."""

    _fields_ = [
        ("nIpCfgOption", C.c_uint),
        ("nIpCfgCurrent", C.c_uint),
        ("nCurrentIp", C.c_uint),
        ("nCurrentSubNetMask", C.c_uint),
        ("nDefultGateWay", C.c_uint),  # опечатка вендора сохранена
        ("chManufacturerName", C.c_ubyte * 32),
        ("chModelName", C.c_ubyte * 32),
        ("chDeviceVersion", C.c_ubyte * 32),
        ("chManufacturerSpecificInfo", C.c_ubyte * 48),
        ("chSerialNumber", C.c_ubyte * 16),
        ("chUserDefinedName", C.c_ubyte * 16),
        ("nNetExport", C.c_uint),
        ("nCurUserIP", C.c_uint),
        ("nAreaLogo", C.c_uint),
        ("chSafeMajorVer", C.c_ubyte),
        ("chSafeMinorVer", C.c_ubyte),
        ("chActive", C.c_ubyte),
        ("chLock", C.c_ubyte),
        ("nLockTime", C.c_ushort),
        ("chSafeAction", C.c_ubyte),
        ("chReserved", C.c_ubyte),
    ]


class USB3_DEVICE_INFO(C.Structure):
    """MV_CODEREADER_USB3_DEVICE_INFO — 540 байт (задаёт размер union SpecialInfo)."""

    _fields_ = [
        ("CrtlInEndPoint", C.c_ubyte),
        ("CrtlOutEndPoint", C.c_ubyte),
        ("StreamEndPoint", C.c_ubyte),
        ("EventEndPoint", C.c_ubyte),
        ("idVendor", C.c_ushort),
        ("idProduct", C.c_ushort),
        ("nDeviceNumber", C.c_uint),
        ("chDeviceGUID", C.c_ubyte * INFO_MAX_BUFFER_SIZE),
        ("chVendorName", C.c_ubyte * INFO_MAX_BUFFER_SIZE),
        ("chModelName", C.c_ubyte * INFO_MAX_BUFFER_SIZE),
        ("chFamilyName", C.c_ubyte * INFO_MAX_BUFFER_SIZE),
        ("chDeviceVersion", C.c_ubyte * INFO_MAX_BUFFER_SIZE),
        ("chManufacturerName", C.c_ubyte * INFO_MAX_BUFFER_SIZE),
        ("chSerialNumber", C.c_ubyte * INFO_MAX_BUFFER_SIZE),
        ("chUserDefinedName", C.c_ubyte * INFO_MAX_BUFFER_SIZE),
        ("nbcdUSB", C.c_uint),
        ("nReserved", C.c_uint * 3),
    ]


class SPECIAL_INFO(C.Union):
    _fields_ = [("stGigEInfo", GIGE_DEVICE_INFO), ("stUsb3VInfo", USB3_DEVICE_INFO)]


class DEVICE_INFO(C.Structure):
    """MV_CODEREADER_DEVICE_INFO — 572 байта."""

    _fields_ = [
        ("nMajorVer", C.c_ushort),
        ("nMinorVer", C.c_ushort),
        ("nMacAddrHigh", C.c_uint),
        ("nMacAddrLow", C.c_uint),
        ("nTLayerType", C.c_uint),
        ("nDeviceType", C.c_uint),
        ("bSelectDevice", C.c_bool),
        ("nWebHostIp", C.c_uint),
        ("nReserved", C.c_uint * 1),
        ("SpecialInfo", SPECIAL_INFO),
    ]


class DEVICE_INFO_LIST(C.Structure):
    """MV_CODEREADER_DEVICE_INFO_LIST — 2056 байт; указатели смотрят в память SDK."""

    _fields_ = [
        ("nDeviceNum", C.c_uint),
        ("pDeviceInfo", C.POINTER(DEVICE_INFO) * MAX_DEVICE_NUM),
    ]


class POINT_I(C.Structure):
    _fields_ = [("x", C.c_int), ("y", C.c_int)]


class CODE_INFO(C.Structure):
    """MV_CODEREADER_CODE_INFO — 200 байт. Оценки осмысленны только при ``bIsGetQuality``."""

    _fields_ = (
        [
            (name, C.c_int)
            for name in (
                "nOverQuality",
                "nDeCode",
                "nSCGrade",
                "nModGrade",
                "nFPDGrade",
                "nANGrade",
                "nGNGrade",
                "nUECGrade",
                "nPGHGrade",
                "nPGVGrade",
            )
        ]
        + [
            (name, C.c_float)
            for name in (
                "fSCScore",
                "fModScore",
                "fFPDScore",
                "fAnScore",
                "fGNScore",
                "fUECScore",
                "fPGHScore",
                "fPGVScore",
            )
        ]
        + [("nRMGrade", C.c_int), ("fRMScore", C.c_float)]
        + [
            (name, C.c_int)
            for name in (
                "n1DEdgeGrade",
                "n1DMinRGrade",
                "n1DMinEGrade",
                "n1DDcdGrade",
                "n1DDefGrade",
                "n1DQZGrade",
            )
        ]
        + [
            (name, C.c_float)
            for name in (
                "f1DEdgeScore",
                "f1DMinRScore",
                "f1DMinEScore",
                "f1DDcdScore",
                "f1DDefScore",
                "f1DQZScore",
            )
        ]
        + [("nReserved", C.c_int * 18)]
    )


class BCR_INFO_EX2(C.Structure):
    """MV_CODEREADER_BCR_INFO_EX2 — 4628 байт, одна запись кода.

    Байты кода — только через :func:`code_bytes`: ``c_char``-массив при чтении
    обрывается на первом нуле, а ``nLen`` — настоящая длина (ревью 6.1, п.2).
    """

    _fields_ = [
        ("nID", C.c_uint),
        ("chCode", C.c_char * MAX_BCR_CODE_LEN_EX),
        ("nLen", C.c_uint),
        ("nBarType", C.c_uint),
        ("pt", POINT_I * 4),
        ("stCodeQuality", CODE_INFO),
        ("nAngle", C.c_int),  # градусы ×10
        ("nMainPackageId", C.c_uint),
        ("nSubPackageId", C.c_uint),
        ("sAppearCount", C.c_ushort),
        ("sPPM", C.c_ushort),  # ×10
        ("sAlgoCost", C.c_ushort),  # мс
        ("sSharpness", C.c_ushort),
        ("bIsGetQuality", C.c_bool),
        ("nIDRScore", C.c_uint),
        ("n1DIsGetQuality", C.c_uint),
        ("nTotalProcCost", C.c_uint),
        ("nTriggerTimeTvHigh", C.c_uint),
        ("nTriggerTimeTvLow", C.c_uint),
        ("nTriggerTimeUtvHigh", C.c_uint),
        ("nTriggerTimeUtvLow", C.c_uint),
        ("sPollingIndex", C.c_ushort),
        ("sRoiIndex", C.c_ushort),
        ("nLightSourceBitMap", C.c_uint),
        ("nReserved", C.c_int * 57),
    ]


def code_bytes(rec: BCR_INFO_EX2) -> bytes:
    """Ровно ``nLen`` байт кода из записи — с нулями внутри, если они есть."""
    length = max(0, min(int(rec.nLen), MAX_BCR_CODE_LEN_EX))
    return C.string_at(C.addressof(rec) + BCR_INFO_EX2.chCode.offset, length)


class RESULT_BCR_EX2(C.Structure):
    """MV_CODEREADER_RESULT_BCR_EX2 — 1 388 436 байт: до 300 записей кодов."""

    _fields_ = [
        ("nCodeNum", C.c_uint),
        ("stBcrInfoEx2", BCR_INFO_EX2 * MAX_BCR_COUNT_EX),
        ("nNoReadNum", C.c_ushort),
        ("nRes", C.c_ushort),
        ("nReserved", C.c_uint * 7),
    ]


class _UNPARSED_BCR_LIST(C.Union):
    _fields_ = [("pstCodeListEx2", C.POINTER(RESULT_BCR_EX2)), ("nAligning", C.c_int64)]


class _UNPARSED_OCR_LIST(C.Union):
    _fields_ = [("pstOcrList", C.c_void_p), ("nAligning", C.c_int64)]


class _UNPARSED_AGV_INFO(C.Union):
    _fields_ = [("pstAgvInfo", C.c_void_p), ("nAligning", C.c_int64)]


class IMAGE_OUT_INFO_EX2(C.Structure):
    """MV_CODEREADER_IMAGE_OUT_INFO_EX2 — 200 байт, описание кадра из GetOneFrameTimeoutEx2."""

    _fields_ = [
        ("nWidth", C.c_ushort),
        ("nHeight", C.c_ushort),
        ("enPixelType", C.c_uint),
        ("nTriggerIndex", C.c_uint),
        ("nFrameNum", C.c_uint),
        ("nFrameLen", C.c_uint),
        ("nTimeStampHigh", C.c_uint),
        ("nTimeStampLow", C.c_uint),
        ("bFlaseTrigger", C.c_uint),  # опечатка вендора сохранена
        ("nFocusScore", C.c_uint),
        ("bIsGetCode", C.c_bool),
        ("pstCodeListEx", C.c_void_p),
        ("pstWaybillList", C.c_void_p),
        ("nEventID", C.c_uint),
        ("nChannelID", C.c_uint),
        ("nImageCost", C.c_uint),
        ("UnparsedBcrList", _UNPARSED_BCR_LIST),
        ("UnparsedOcrList", _UNPARSED_OCR_LIST),
        ("nWholeFlag", C.c_ushort),
        ("nRes", C.c_ushort),
        ("UnparsedAgvInfo", _UNPARSED_AGV_INFO),
        ("nReserved", C.c_uint * 23),
    ]
