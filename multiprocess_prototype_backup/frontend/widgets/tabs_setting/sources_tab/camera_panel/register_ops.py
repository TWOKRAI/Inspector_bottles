# multiprocess_prototype/frontend/widgets/camera_tab/register_ops.py
"""Работа с CAMERA_REGISTER: camera_type. Hikvision-специфичные ops — в hikvision_widget."""

from __future__ import annotations

from typing import Any, Optional

from multiprocess_framework.modules.frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype.frontend.actions.builder import ActionBuilder
from multiprocess_prototype.registers.constants import CAMERA_REGISTER


def set_camera_type_field(
    rm: Optional[IRegistersManagerGui], camera_type: str
) -> None:
    """Записать строковый тип камеры в CAMERA_REGISTER.camera_type."""
    if rm is not None:
        rm.set_field_value(CAMERA_REGISTER, "camera_type", camera_type)


def set_camera_type_via_bus(
    bus: Optional[Any],
    rm: Optional[IRegistersManagerGui],
    camera_type: str,
) -> None:
    """Записать camera_type через ActionBus (undo-able) или fallback на rm."""
    if bus is None:
        set_camera_type_field(rm, camera_type)
        return
    old = rm.get_field_value(CAMERA_REGISTER, "camera_type") if rm else None
    action = ActionBuilder.field_set(
        CAMERA_REGISTER,
        "camera_type",
        camera_type,
        old,
        description=f"Тип камеры: {camera_type}",
    )
    bus.execute(action)


def persist_camera_type(camera_type: str) -> None:
    """Сохранить тип камеры на диск."""
    try:
        from multiprocess_prototype.persistence import set_camera_type

        set_camera_type(camera_type)
    except Exception:
        pass
