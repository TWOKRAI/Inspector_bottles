# -*- coding: utf-8 -*-
"""
CameraRegisters — параметры камеры (тип, FPS, разрешение).

Маршрутизация: camera.
"""
from typing import Annotated, ClassVar

from multiprocess_prototype.camera_policy import CameraTypeStr, DEFAULT_CAMERA_TYPE

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

CAMERA_ROUTING = FieldRouting(channel="control_camera")


class CameraRegisters(SchemaBase):
    """Регистры параметров камеры."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("camera",),
    )

    camera_type: Annotated[
        CameraTypeStr,
        FieldMeta(
            "Тип камеры",
            info="Simulator, Webcam или Hikvision.",
            routing=CAMERA_ROUTING,
        ),
    ] = DEFAULT_CAMERA_TYPE

    fps: Annotated[
        int,
        FieldMeta(
            "FPS",
            info="Частота кадров (1–120).",
            min=1,
            max=120,
            unit="fps",
            routing=CAMERA_ROUTING,
        ),
    ] = 25

    resolution_width: Annotated[
        int,
        FieldMeta(
            "Ширина",
            info="Ширина кадра (Simulator/Webcam).",
            min=320,
            max=1920,
            unit="px",
            routing=CAMERA_ROUTING,
        ),
    ] = 640

    resolution_height: Annotated[
        int,
        FieldMeta(
            "Высота",
            info="Высота кадра (Simulator/Webcam).",
            min=240,
            max=1080,
            unit="px",
            routing=CAMERA_ROUTING,
        ),
    ] = 480

    device_id: Annotated[
        int,
        FieldMeta(
            "ID устройства",
            info="Индекс устройства Webcam / OpenCV (0…63, см. enum_devices).",
            min=0,
            max=63,
            routing=CAMERA_ROUTING,
        ),
    ] = 0

    camera_index: Annotated[
        int,
        FieldMeta(
            "Индекс Hikvision",
            info="Индекс в списке MV_CC_EnumDevices (0…63).",
            min=0,
            max=63,
            routing=CAMERA_ROUTING,
        ),
    ] = 0

    hikvision_resolution_width: Annotated[
        int,
        FieldMeta(
            "Ширина Hikvision",
            info="Ширина кадра Hikvision.",
            min=320,
            max=4096,
            unit="px",
            routing=CAMERA_ROUTING,
        ),
    ] = 1920

    hikvision_resolution_height: Annotated[
        int,
        FieldMeta(
            "Высота Hikvision",
            info="Высота кадра Hikvision.",
            min=240,
            max=4096,
            unit="px",
            routing=CAMERA_ROUTING,
        ),
    ] = 1080

    hikvision_frame_rate: Annotated[
        float,
        FieldMeta(
            "Frame Rate Hikvision",
            info="Частота кадров Hikvision (Get/Set Parameters).",
            min=0.1,
            max=120.0,
            unit="fps",
            routing=CAMERA_ROUTING,
        ),
    ] = 25.0

    hikvision_exposure_time: Annotated[
        float,
        FieldMeta(
            "Exposure Hikvision",
            info="Время экспозиции Hikvision (μs).",
            min=0.0,
            max=1000000.0,
            unit="μs",
            routing=CAMERA_ROUTING,
        ),
    ] = 10000.0

    hikvision_gain: Annotated[
        float,
        FieldMeta(
            "Gain Hikvision",
            info="Усиление Hikvision (dB).",
            min=0.0,
            max=24.0,
            unit="dB",
            routing=CAMERA_ROUTING,
        ),
    ] = 0.0
