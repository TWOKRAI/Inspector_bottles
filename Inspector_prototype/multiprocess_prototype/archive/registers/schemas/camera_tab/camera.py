# -*- coding: utf-8 -*-
"""
Схемы регистров камеры: стандарт (Simulator/Webcam) и расширение Hikvision.

Публичное имя регистра процесса — :data:`CameraRegisters` (полный набор полей).

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


class StandardCameraRegisters(SchemaBase):
    """Регистры общих параметров камеры (Simulator / Webcam): тип, FPS, разрешение, устройство."""

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



class HikvisionCameraRegisters(StandardCameraRegisters):
    """Дополнительные поля для камеры Hikvision (индекс SDK, разрешение, экспозиция, gain)."""

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
            "Частота кадров Hikvision",
            info="Частота кадров Hikvision (Get/Set Parameters).",
            min=1,
            max=120,
            unit="fps",
            routing=CAMERA_ROUTING,
        ),
    ] = 25.0

    hikvision_exposure_time: Annotated[
        float,
        FieldMeta(
            "Экспозиция Hikvision",
            info="Время экспозиции Hikvision (μs).",
            min=1,
            max=100000,
            unit="μs",
            routing=CAMERA_ROUTING,
        ),
    ] = 10000.0

    hikvision_gain: Annotated[
        float,
        FieldMeta(
            "Усиление Hikvision",
            info="Усиление Hikvision (dB).",
            min=0.0,
            max=24.0,
            unit="dB",
            routing=CAMERA_ROUTING,
        ),
    ] = 0.0


# Полная схема регистра `camera` (обратная совместимость импорта).
CameraRegisters = HikvisionCameraRegisters
