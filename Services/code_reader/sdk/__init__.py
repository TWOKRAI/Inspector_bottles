# -*- coding: utf-8 -*-
"""Слой MvCodeReader SDK (``MvCodeReaderCtrl.dll``): загрузка, структуры, тонкая обёртка.

Чистый сервисный слой: ничего из ``multiprocess_framework``. Импорт пакета DLL не
грузит — это делает первый вызов ``MvCodeReaderApi`` (или ``load_library``).
"""

from __future__ import annotations

from .api import DeviceEntry, MvCodeReaderApi, RawFrame
from .errors import E_ACCESS_DENIED, E_NODATA, MV_OK, SdkError, SdkNotFoundError
from .loader import IDMVS_PLUGIN_DIR, find_sdk_dir, load_library
from .structures import BAR_TYPE_NOREAD, GIGE_DEVICE, PIXEL_JPEG, PIXEL_MONO8

__all__ = [
    "BAR_TYPE_NOREAD",
    "E_ACCESS_DENIED",
    "E_NODATA",
    "GIGE_DEVICE",
    "IDMVS_PLUGIN_DIR",
    "MV_OK",
    "PIXEL_JPEG",
    "PIXEL_MONO8",
    "DeviceEntry",
    "MvCodeReaderApi",
    "RawFrame",
    "SdkError",
    "SdkNotFoundError",
    "find_sdk_dir",
    "load_library",
]
