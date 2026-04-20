"""Camera register schemas: base types and GUI flat register."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

from ..constants import (
    CAMERA_ROUTING,
    DEFAULT_FPS,
    DEFAULT_HIKVISION_HEIGHT,
    DEFAULT_HIKVISION_WIDTH,
    DEFAULT_RESOLUTION_HEIGHT,
    DEFAULT_RESOLUTION_WIDTH,
)
from .policy import CameraTypeStr, DEFAULT_CAMERA_TYPE


@register_schema("BaseCameraRegistersV3")
class BaseCameraRegisters(SchemaBase):
    """Common camera parameters (base for all camera types)."""

    camera_type: Annotated[
        CameraTypeStr,
        FieldMeta("Тип камеры", info="Simulator, Webcam или Hikvision.", routing=CAMERA_ROUTING),
    ] = DEFAULT_CAMERA_TYPE

    fps: Annotated[
        int,
        FieldMeta("FPS", info="Частота кадров (1..120).", min=1, max=120, unit="fps", routing=CAMERA_ROUTING),
    ] = DEFAULT_FPS

    resolution_width: Annotated[
        int,
        FieldMeta("Ширина", info="Ширина кадра.", min=320, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = DEFAULT_RESOLUTION_WIDTH

    resolution_height: Annotated[
        int,
        FieldMeta("Высота", info="Высота кадра.", min=240, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = DEFAULT_RESOLUTION_HEIGHT


@register_schema("WebcamCameraRegistersV3")
class WebcamCameraRegisters(BaseCameraRegisters):
    """Webcam camera parameters (used in Pipeline schema)."""

    camera_type: Annotated[
        Literal["webcam"],
        FieldMeta("Тип камеры", info="Webcam.", routing=CAMERA_ROUTING),
    ] = "webcam"

    device_id: Annotated[
        int,
        FieldMeta("ID устройства", info="Индекс Webcam (0..63).", min=0, max=63, routing=CAMERA_ROUTING),
    ] = 0


@register_schema("HikvisionCameraRegistersV3")
class HikvisionCameraRegisters(BaseCameraRegisters):
    """Hikvision camera parameters (used in Pipeline schema)."""

    camera_type: Annotated[
        Literal["hikvision"],
        FieldMeta("Тип камеры", info="Hikvision.", routing=CAMERA_ROUTING),
    ] = "hikvision"

    camera_index: Annotated[
        int,
        FieldMeta("Индекс Hikvision", info="Индекс устройства (0..63).", min=0, max=63, routing=CAMERA_ROUTING),
    ] = 0

    hikvision_resolution_width: Annotated[
        int,
        FieldMeta("Ширина Hikvision", info="Ширина кадра.", min=320, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = DEFAULT_HIKVISION_WIDTH

    hikvision_resolution_height: Annotated[
        int,
        FieldMeta("Высота Hikvision", info="Высота кадра.", min=240, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = DEFAULT_HIKVISION_HEIGHT

    hikvision_frame_rate: Annotated[
        float,
        FieldMeta("Частота кадров Hikvision", info="FPS.", min=1, max=120, unit="fps", routing=CAMERA_ROUTING),
    ] = float(DEFAULT_FPS)

    hikvision_exposure_time: Annotated[
        float,
        FieldMeta("Экспозиция Hikvision", info="Время экспозиции (us).", min=1, max=100000, unit="us", routing=CAMERA_ROUTING),
    ] = 10000.0

    hikvision_gain: Annotated[
        float,
        FieldMeta("Усиление Hikvision", info="Усиление сигнала.", min=0.0, max=24.0, unit="dB", routing=CAMERA_ROUTING),
    ] = 0.0


@register_schema("GuiCameraRegistersV3")
class GuiCameraRegisters(BaseCameraRegisters):
    """Flat camera register for GUI/RegistersManager (all fields in one register)."""

    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("camera",),
    )

    device_id: Annotated[
        int,
        FieldMeta("ID устройства", info="Индекс Webcam (0..63).", min=0, max=63, routing=CAMERA_ROUTING),
    ] = 0

    camera_index: Annotated[
        int,
        FieldMeta("Индекс Hikvision", info="Индекс устройства (0..63).", min=0, max=63, routing=CAMERA_ROUTING),
    ] = 0

    hikvision_resolution_width: Annotated[
        int,
        FieldMeta("Ширина Hikvision", info="Ширина кадра.", min=320, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = DEFAULT_HIKVISION_WIDTH

    hikvision_resolution_height: Annotated[
        int,
        FieldMeta("Высота Hikvision", info="Высота кадра.", min=240, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = DEFAULT_HIKVISION_HEIGHT

    hikvision_frame_rate: Annotated[
        float,
        FieldMeta("Частота кадров Hikvision", info="FPS.", min=1, max=120, unit="fps", routing=CAMERA_ROUTING),
    ] = float(DEFAULT_FPS)

    hikvision_exposure_time: Annotated[
        float,
        FieldMeta("Экспозиция Hikvision", info="Время экспозиции (us).", min=1, max=100000, unit="us", routing=CAMERA_ROUTING),
    ] = 10000.0

    hikvision_gain: Annotated[
        float,
        FieldMeta("Усиление Hikvision", info="Усиление сигнала.", min=0.0, max=24.0, unit="dB", routing=CAMERA_ROUTING),
    ] = 0.0


__all__ = [
    "BaseCameraRegisters",
    "WebcamCameraRegisters",
    "HikvisionCameraRegisters",
    "GuiCameraRegisters",
]
