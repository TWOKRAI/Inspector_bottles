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

    # --- Recorder (AD-10) ---
    record_video: Annotated[
        bool,
        FieldMeta("Запись видео", info="Включить/выключить запись.", routing=CAMERA_ROUTING),
    ] = False

    record_path: Annotated[
        str,
        FieldMeta("Путь записи", info="Директория для файлов записи.", routing=CAMERA_ROUTING),
    ] = ""

    record_codec: Annotated[
        str,
        FieldMeta("Кодек записи", info="Кодек VideoWriter (mp4v, XVID, H264).", routing=CAMERA_ROUTING),
    ] = "mp4v"

    max_record_minutes: Annotated[
        int,
        FieldMeta("Макс. длина записи", info="Авто-разделение файла (мин).", min=1, max=1440, unit="мин", routing=CAMERA_ROUTING),
    ] = 30

    # --- History buffer (AD-9, Phase 3.5) ---
    history_enabled: Annotated[
        bool,
        FieldMeta("Буфер истории", info="Включить JPEG-буфер для перемотки.", routing=CAMERA_ROUTING),
    ] = False

    history_duration_sec: Annotated[
        int,
        FieldMeta("Длительность истории", info="Глубина буфера (сек).", min=10, max=600, unit="сек", routing=CAMERA_ROUTING),
    ] = 120

    history_jpeg_quality: Annotated[
        int,
        FieldMeta("Качество JPEG истории", info="Качество сжатия (1..100).", min=1, max=100, routing=CAMERA_ROUTING),
    ] = 80


__all__ = [
    "BaseCameraRegisters",
    "WebcamCameraRegisters",
    "HikvisionCameraRegisters",
    "GuiCameraRegisters",
]
