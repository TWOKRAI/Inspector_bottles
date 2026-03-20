# -*- coding: utf-8 -*-
"""
CameraRegisters — параметры камеры (тип, FPS, разрешение).

Маршрутизация: camera.
"""
from typing import Annotated, ClassVar, Literal

from multiprocess_framework.refactored.modules.data_schema_module import (
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
        Literal["simulator", "webcam", "hikvision"],
        FieldMeta(
            "Тип камеры",
            info="Simulator, Webcam или Hikvision.",
            routing=CAMERA_ROUTING,
        ),
    ] = "simulator"

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
            info="Индекс устройства Webcam (0–10).",
            min=0,
            max=10,
            routing=CAMERA_ROUTING,
        ),
    ] = 0

    camera_index: Annotated[
        int,
        FieldMeta(
            "Индекс Hikvision",
            info="Индекс камеры Hikvision.",
            min=0,
            max=10,
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
