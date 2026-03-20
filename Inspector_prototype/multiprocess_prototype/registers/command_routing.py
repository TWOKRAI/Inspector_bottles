# multiprocess_prototype/registers/command_routing.py
"""
Маршрутизация GUI-команд к процессам по схемам регистров.

Единый источник targets для send_message: process_targets из RegisterDispatchMeta
на классах CameraRegisters / ProcessorRegisters / RendererRegisters.
Исключения (не привязаны к регистру) — в EXPLICIT_COMMAND_TARGETS.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, List, Tuple, Type

from multiprocess_prototype.registers.schemas.camera_tab import (
    CAMERA_REGISTER,
    CameraRegisters,
)
from multiprocess_prototype.registers.schemas.processing_tab import (
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
    ProcessorRegisters,
    RendererRegisters,
)

# Имя регистра → класс схемы (для register_dispatch.process_targets)
REGISTER_SCHEMA_BY_NAME: Dict[str, Type] = {
    CAMERA_REGISTER: CameraRegisters,
    PROCESSOR_REGISTER: ProcessorRegisters,
    RENDERER_REGISTER: RendererRegisters,
}

# Команда → ключ регистра (совпадает с RegistersManager / factory)
COMMAND_TO_REGISTER_KEY: Dict[str, str] = {
    # camera
    "start_capture": CAMERA_REGISTER,
    "stop_capture": CAMERA_REGISTER,
    "set_fps": CAMERA_REGISTER,
    "enum_devices": CAMERA_REGISTER,
    "open": CAMERA_REGISTER,
    "close": CAMERA_REGISTER,
    "start_grabbing": CAMERA_REGISTER,
    "stop_grabbing": CAMERA_REGISTER,
    "get_parameters": CAMERA_REGISTER,
    "set_parameters": CAMERA_REGISTER,
    "set_camera_type": CAMERA_REGISTER,
    # processor
    "set_color_range": PROCESSOR_REGISTER,
    "set_min_area": PROCESSOR_REGISTER,
    "set_max_area": PROCESSOR_REGISTER,
    # renderer
    "set_show_original": RENDERER_REGISTER,
    "set_show_mask": RENDERER_REGISTER,
    "set_draw_contours": RENDERER_REGISTER,
}

# Команды без регистра (оркестратор и т.п.)
EXPLICIT_COMMAND_TARGETS: Dict[str, Tuple[str, ...]] = {
    "system.shutdown": ("ProcessManager",),
}


def resolve_command_targets(command_id: str) -> List[str]:
    """
    Список имён процессов для поля ``targets`` сообщения command.

    Raises:
        KeyError: неизвестная команда.
        RuntimeError: у схемы нет register_dispatch / пустые process_targets.
    """
    if command_id in EXPLICIT_COMMAND_TARGETS:
        return list(EXPLICIT_COMMAND_TARGETS[command_id])
    reg_key = COMMAND_TO_REGISTER_KEY.get(command_id)
    if reg_key is None:
        raise KeyError(
            f"Unknown GUI command_id {command_id!r}: "
            "add to COMMAND_TO_REGISTER_KEY or EXPLICIT_COMMAND_TARGETS"
        )
    cls = REGISTER_SCHEMA_BY_NAME[reg_key]
    meta = getattr(cls, "register_dispatch", None)
    if meta is None:
        raise RuntimeError(f"No register_dispatch on {cls.__name__}")
    targets = tuple(getattr(meta, "process_targets", None) or ())
    if not targets:
        raise RuntimeError(f"Empty process_targets for register {reg_key!r}")
    return list(targets)


def list_gui_command_ids() -> FrozenSet[str]:
    """Все command_id, известные маршрутизатору (для тестов и валидации каталога)."""
    return frozenset(COMMAND_TO_REGISTER_KEY) | frozenset(EXPLICIT_COMMAND_TARGETS)
