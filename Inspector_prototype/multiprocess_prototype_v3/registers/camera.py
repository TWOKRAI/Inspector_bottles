"""Camera register schemas — types, policies, and GUI registers."""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal, Tuple

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
    register_schema,
)

# --- Camera type policy ---
CameraTypeStr = Literal["simulator", "webcam", "hikvision"]
CAMERA_TYPES: Tuple[CameraTypeStr, ...] = ("simulator", "webcam", "hikvision")
DEFAULT_CAMERA_TYPE: CameraTypeStr = "simulator"
CAMERA_TYPE_LABELS: Tuple[str, ...] = ("Simulator", "Webcam", "Hikvision")
SUPPORTS_ENUM: Tuple[str, ...] = ("webcam", "hikvision")
SUPPORTS_HARDWARE_HANDOFF: Tuple[str, ...] = ("webcam", "hikvision")
WEBCAM_ENUM_DEFAULT_MAX_INDEX = 32
WEBCAM_ENUM_HARD_CAP = 64

CAMERA_ROUTING = FieldRouting(channel="control_camera")


@register_schema("BaseCameraRegistersV3")
class BaseCameraRegisters(SchemaBase):
    """Common camera parameters."""

    camera_type: Annotated[
        CameraTypeStr,
        FieldMeta("Тип камеры", info="Simulator, Webcam или Hikvision.", routing=CAMERA_ROUTING),
    ] = DEFAULT_CAMERA_TYPE

    fps: Annotated[
        int,
        FieldMeta("FPS", info="Частота кадров (1..120).", min=1, max=120, unit="fps", routing=CAMERA_ROUTING),
    ] = 25

    resolution_width: Annotated[
        int,
        FieldMeta("Ширина", info="Ширина кадра.", min=320, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = 640

    resolution_height: Annotated[
        int,
        FieldMeta("Высота", info="Высота кадра.", min=240, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = 480


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
        FieldMeta("Индекс Hikvision", info="Индекс устройства Hikvision (0..63).", min=0, max=63, routing=CAMERA_ROUTING),
    ] = 0

    hikvision_resolution_width: Annotated[
        int,
        FieldMeta("Ширина Hikvision", info="Ширина кадра Hikvision.", min=320, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = 1920

    hikvision_resolution_height: Annotated[
        int,
        FieldMeta("Высота Hikvision", info="Высота кадра Hikvision.", min=240, max=4096, unit="px", routing=CAMERA_ROUTING),
    ] = 1080

    hikvision_frame_rate: Annotated[
        float,
        FieldMeta("Частота кадров Hikvision", info="Частота кадров Hikvision.", min=1, max=120, unit="fps", routing=CAMERA_ROUTING),
    ] = 25.0

    hikvision_exposure_time: Annotated[
        float,
        FieldMeta("Экспозиция Hikvision", info="Время экспозиции (us).", min=1, max=100000, unit="us", routing=CAMERA_ROUTING),
    ] = 10000.0

    hikvision_gain: Annotated[
        float,
        FieldMeta("Усиление Hikvision", info="Усиление сигнала.", min=0.0, max=24.0, unit="dB", routing=CAMERA_ROUTING),
    ] = 0.0
