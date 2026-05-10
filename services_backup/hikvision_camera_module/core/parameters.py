# -*- coding: utf-8 -*-
"""
Get/set параметров камеры Hikvision: frame_rate, exposure_time, gain.
"""

import time
from ctypes import byref, memset, sizeof
from typing import Any, Dict

try:
    from hikvision_camera_module.sdk.MvCameraControl_class import (
        MVCC_FLOATVALUE,
    )

    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False
    MVCC_FLOATVALUE = None


def get_parameters(camera: Any) -> Dict[str, Any]:
    """
    Получить параметры камеры.
    Returns: {status: "ok"|"error", parameters: {frame_rate, exposure_time, gain}}
    """
    if not _SDK_AVAILABLE or camera is None:
        return {"status": "error", "parameters": {}}
    try:
        st_fr = MVCC_FLOATVALUE()
        memset(byref(st_fr), 0, sizeof(st_fr))
        st_exp = MVCC_FLOATVALUE()
        memset(byref(st_exp), 0, sizeof(st_exp))
        st_gain = MVCC_FLOATVALUE()
        memset(byref(st_gain), 0, sizeof(st_gain))
        if camera.MV_CC_GetFloatValue("AcquisitionFrameRate", st_fr) != 0:
            return {"status": "error", "parameters": {}}
        if camera.MV_CC_GetFloatValue("ExposureTime", st_exp) != 0:
            return {"status": "error", "parameters": {}}
        if camera.MV_CC_GetFloatValue("Gain", st_gain) != 0:
            return {"status": "error", "parameters": {}}
        return {
            "status": "ok",
            "parameters": {
                "frame_rate": st_fr.fCurValue,
                "exposure_time": st_exp.fCurValue,
                "gain": st_gain.fCurValue,
            },
        }
    except Exception:
        return {"status": "error", "parameters": {}}


def set_parameters(
    camera: Any,
    frame_rate: float,
    exposure_time: float,
    gain: float,
) -> Dict[str, Any]:
    """
    Установить параметры камеры.
    Returns: {status: "ok"|"error"}
    """
    if not _SDK_AVAILABLE or camera is None:
        return {"status": "error"}
    try:
        camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)
        camera.MV_CC_SetEnumValue("ExposureAuto", 0)
        time.sleep(0.2)
        if camera.MV_CC_SetFloatValue("ExposureTime", float(exposure_time)) != 0:
            return {"status": "error"}
        if camera.MV_CC_SetFloatValue("Gain", float(gain)) != 0:
            return {"status": "error"}
        if camera.MV_CC_SetFloatValue("AcquisitionFrameRate", float(frame_rate)) != 0:
            return {"status": "error"}
        return {"status": "ok"}
    except Exception:
        return {"status": "error"}
