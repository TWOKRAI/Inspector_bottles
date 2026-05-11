"""Runtime-параметры Hikvision камеры (управляемые из GUI)."""
from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import register_schema
from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.data_schema_module import SchemaBase


@register_schema("HikvisionCameraRegistersV1")
class HikvisionCameraRegisters(SchemaBase):
    """Runtime-параметры Hikvision камеры.

    Эти параметры можно менять на лету через GUI:
    - exposure_time -- время экспозиции
    - gain -- усиление
    - frame_rate -- частота кадров

    Значения синхронизируются с SDK камеры через _apply_parameters_from_register().
    """

    exposure_time: Annotated[
        float,
        FieldMeta(
            description="Время экспозиции (мкс)",
            min=10.0,
            max=1_000_000.0,
            unit="мкс",
        ),
    ] = 10_000.0

    gain: Annotated[
        float,
        FieldMeta(
            description="Усиление (дБ)",
            min=0.0,
            max=20.0,
            unit="дБ",
        ),
    ] = 0.0

    frame_rate: Annotated[
        float,
        FieldMeta(
            description="Частота кадров (fps)",
            min=1.0,
            max=120.0,
            unit="fps",
        ),
    ] = 25.0
