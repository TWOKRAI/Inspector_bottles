# -*- coding: utf-8 -*-
"""
Чтение и запись параметров камеры: frame_rate, exposure_time, gain.

Возвращает типизированный CameraParameters dataclass вместо dict.
Использует check_sdk_error для явного контроля ошибок.
"""

from __future__ import annotations

import time
from ctypes import byref, memset, sizeof
from dataclasses import dataclass

from Services.hikvision_camera.sdk.bindings import MvCamera, SDK_AVAILABLE
from Services.hikvision_camera.sdk.structures import MVCC_FLOATVALUE
from Services.hikvision_camera.sdk.errors import check_sdk_error, SdkError


@dataclass
class CameraParameters:
    """Параметры камеры."""

    frame_rate: float = 0.0
    exposure_time: float = 0.0
    gain: float = 0.0


def get_parameters(camera: MvCamera) -> CameraParameters | None:
    """Получить текущие параметры камеры.

    Parameters
    ----------
    camera : MvCamera
        Экземпляр SDK-камеры (должен быть открыт).

    Returns
    -------
    CameraParameters | None
        Параметры камеры или None при ошибке.
    """
    if not SDK_AVAILABLE or camera is None:
        return None

    try:
        st_fr = MVCC_FLOATVALUE()
        memset(byref(st_fr), 0, sizeof(st_fr))

        st_exp = MVCC_FLOATVALUE()
        memset(byref(st_exp), 0, sizeof(st_exp))

        st_gain = MVCC_FLOATVALUE()
        memset(byref(st_gain), 0, sizeof(st_gain))

        check_sdk_error(
            camera.MV_CC_GetFloatValue("AcquisitionFrameRate", st_fr),
            "get_frame_rate",
        )
        check_sdk_error(
            camera.MV_CC_GetFloatValue("ExposureTime", st_exp),
            "get_exposure_time",
        )
        check_sdk_error(
            camera.MV_CC_GetFloatValue("Gain", st_gain),
            "get_gain",
        )

        return CameraParameters(
            frame_rate=st_fr.fCurValue,
            exposure_time=st_exp.fCurValue,
            gain=st_gain.fCurValue,
        )

    except SdkError:
        return None
    except Exception:
        return None


def set_parameters(camera: MvCamera, params: CameraParameters) -> bool:
    """Установить параметры камеры.

    Включает frame rate enable, выключает auto exposure, затем
    устанавливает exposure_time, gain, frame_rate.

    Parameters
    ----------
    camera : MvCamera
        Экземпляр SDK-камеры (должен быть открыт).
    params : CameraParameters
        Новые параметры.

    Returns
    -------
    bool
        True если все параметры установлены успешно.
    """
    if not SDK_AVAILABLE or camera is None:
        return False

    try:
        # Включаем ручной контроль fps
        camera.MV_CC_SetBoolValue("AcquisitionFrameRateEnable", True)

        # Выключаем автоэкспозицию
        camera.MV_CC_SetEnumValue("ExposureAuto", 0)
        # Задержка для стабилизации после отключения автоэкспозиции
        time.sleep(0.2)

        check_sdk_error(
            camera.MV_CC_SetFloatValue("ExposureTime", float(params.exposure_time)),
            "set_exposure_time",
        )
        check_sdk_error(
            camera.MV_CC_SetFloatValue("Gain", float(params.gain)),
            "set_gain",
        )
        check_sdk_error(
            camera.MV_CC_SetFloatValue("AcquisitionFrameRate", float(params.frame_rate)),
            "set_frame_rate",
        )

        return True

    except SdkError:
        return False
    except Exception:
        return False
