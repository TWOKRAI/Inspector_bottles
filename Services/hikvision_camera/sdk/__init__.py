# -*- coding: utf-8 -*-
"""Hikvision SDK -- минимальный публичный API.

Реэкспортирует только реально используемые классы, структуры и константы.
"""

from __future__ import annotations

from .bindings import MvCamera, SDK_AVAILABLE
from .structures import (
    MV_CC_DEVICE_INFO_LIST,
    MV_CC_DEVICE_INFO,
    MV_FRAME_OUT,
    MV_FRAME_OUT_INFO,
    MV_GIGE_DEVICE_INFO,
    MV_USB3_DEVICE_INFO,
    MVCC_FLOATVALUE,
    MVCC_INTVALUE,
    MVCC_ENUMVALUE,
    MVCC_STRINGVALUE,
)
from .constants import (
    MV_GIGE_DEVICE,
    MV_USB_DEVICE,
    MV_TRIGGER_MODE_OFF,
    MV_TRIGGER_MODE_ON,
    MV_EXPOSURE_AUTO_MODE_OFF,
    MV_ACCESS_Exclusive,
    MV_ACCESS_Control,
    PixelType,
    MV_MAX_DEVICE_NUM,
    INFO_MAX_BUFFER_SIZE,
)
from .errors import (
    MV_OK,
    SdkError,
    check_sdk_error,
    error_description,
)

__all__ = [
    # bindings
    "MvCamera",
    "SDK_AVAILABLE",
    # structures
    "MV_CC_DEVICE_INFO_LIST",
    "MV_CC_DEVICE_INFO",
    "MV_FRAME_OUT",
    "MV_FRAME_OUT_INFO",
    "MV_GIGE_DEVICE_INFO",
    "MV_USB3_DEVICE_INFO",
    "MVCC_FLOATVALUE",
    "MVCC_INTVALUE",
    "MVCC_ENUMVALUE",
    "MVCC_STRINGVALUE",
    # constants
    "MV_GIGE_DEVICE",
    "MV_USB_DEVICE",
    "MV_TRIGGER_MODE_OFF",
    "MV_TRIGGER_MODE_ON",
    "MV_EXPOSURE_AUTO_MODE_OFF",
    "MV_ACCESS_Exclusive",
    "MV_ACCESS_Control",
    "PixelType",
    "MV_MAX_DEVICE_NUM",
    "INFO_MAX_BUFFER_SIZE",
    # errors
    "MV_OK",
    "SdkError",
    "check_sdk_error",
    "error_description",
]
