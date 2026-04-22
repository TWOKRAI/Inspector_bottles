# multiprocess_prototype_v3/frontend/widgets/camera_tab/register_ops.py
"""Работа с CAMERA_REGISTER: camera_type. Hikvision-специфичные ops — в hikvision_widget."""

from __future__ import annotations

from typing import Optional

from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype_v3.registers.schemas.camera_tab import CAMERA_REGISTER


def set_camera_type_field(
    rm: Optional[IRegistersManagerGui], camera_type: str
) -> None:
    """Записать строковый тип камеры в CAMERA_REGISTER.camera_type."""
    if rm is not None:
        rm.set_field_value(CAMERA_REGISTER, "camera_type", camera_type)


def persist_camera_type(camera_type: str) -> None:
    """Сохранить тип камеры на диск."""
    try:
        from multiprocess_prototype_v3.persistence import set_camera_type

        set_camera_type(camera_type)
    except Exception:
        pass
