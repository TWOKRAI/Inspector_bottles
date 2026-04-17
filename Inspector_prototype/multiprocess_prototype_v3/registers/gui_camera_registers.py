# -*- coding: utf-8 -*-
"""Плоская схема камеры для GUI/RegistersManager (все поля в одном регистре)."""

from __future__ import annotations

from typing import Annotated, ClassVar

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterDispatchMeta,
    register_schema,
)

from multiprocess_prototype_v3.registers.camera import CAMERA_ROUTING, BaseCameraRegisters


@register_schema("GuiCameraRegistersV3")
class GuiCameraRegisters(BaseCameraRegisters):
    """Базовые поля камеры + device_id / Hikvision (неиспользуемые поля допустимы для simulator)."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("camera",),
    )

    device_id: Annotated[
        int,
        FieldMeta(
            "ID устройства",
            info="Индекс Webcam (0..63).",
            min=0,
            max=63,
            routing=CAMERA_ROUTING,
        ),
    ] = 0

    camera_index: Annotated[
        int,
        FieldMeta(
            "Индекс Hikvision",
            info="Индекс устройства Hikvision (0..63).",
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
            info="Частота кадров Hikvision.",
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
            info="Время экспозиции (us).",
            min=1,
            max=100000,
            unit="us",
            routing=CAMERA_ROUTING,
        ),
    ] = 10000.0

    hikvision_gain: Annotated[
        float,
        FieldMeta(
            "Усиление Hikvision",
            info="Усиление сигнала.",
            min=0.0,
            max=24.0,
            unit="dB",
            routing=CAMERA_ROUTING,
        ),
    ] = 0.0
