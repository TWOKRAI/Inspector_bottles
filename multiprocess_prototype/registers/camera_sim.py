# multiprocess_prototype/registers/camera_sim.py
"""Регистры эмулятора камеры."""

from __future__ import annotations

from typing import Annotated, ClassVar

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterDispatchMeta,
    SchemaBase,
)

from .names import CAMERA_SIM_REGISTER

_CAM_R = FieldRouting(channel="control", process_targets=("camera_sim",))


class CameraSimRegisters(SchemaBase):
    register_dispatch: ClassVar[RegisterDispatchMeta] = RegisterDispatchMeta(
        process_targets=("camera_sim",),
    )
    fps: Annotated[int, FieldMeta("FPS", min=1, max=60, routing=_CAM_R)] = 10
    resolution_width: Annotated[int, FieldMeta("Width", min=64, max=1920, routing=_CAM_R)] = 640
    resolution_height: Annotated[int, FieldMeta("Height", min=64, max=1080, routing=_CAM_R)] = 480
    frame_color: Annotated[str, FieldMeta("Color hint", routing=_CAM_R)] = "noise"


def register_name() -> str:
    return CAMERA_SIM_REGISTER
