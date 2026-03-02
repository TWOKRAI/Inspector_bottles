# -*- coding: utf-8 -*-
"""
Модуль регистров для App Inspector.

Архитектура:
    models/registers/ — RegisterBase-классы с FieldMeta (параметры с метаданными)
    models/data/      — BaseModel-классы (структурированные данные без UI-метаданных)
    manager.py        — RegistersManager (фасад над RegistersContainer)

Быстрый старт:

    from App.Registers import RegistersManager

    rm = RegistersManager()
    rm.draw.dp                              # → 1.4
    rm.get_field_metadata("draw", "dp")     # → {"description": ..., "min": 0.1, ...}
    rm.draw.update_field("dp", 2.0)         # → (True, None)
    rm.to_json()                            # → JSON со всеми регистрами

Работа с дата-моделями:

    from App.Registers import CameraData, RegionData
    cam = CameraData(name="cam_01")
"""
from .models import (
    DrawRegisters,
    CameraRegisters,
    ProcessingRegisters,
    PostProcessingRegisters,
    VisualRegisters,
    ConveyorRegisters,
    FrameProcessRegisters,
    HikvisionRegisters,
    NeurounRegisters,
    RobotRegisters,
    CameraData,
    RegionData,
    ChainStepData,
)
from .manager import RegistersManager, DEFAULT_REGISTERS_PACKAGE, DEFAULT_DATA_PACKAGE

__all__ = [
    # Регистры
    "DrawRegisters",
    "CameraRegisters",
    "ProcessingRegisters",
    "PostProcessingRegisters",
    "VisualRegisters",
    "ConveyorRegisters",
    "FrameProcessRegisters",
    "HikvisionRegisters",
    "NeurounRegisters",
    "RobotRegisters",
    # Данные
    "CameraData",
    "RegionData",
    "ChainStepData",
    # Менеджер
    "RegistersManager",
    "DEFAULT_REGISTERS_PACKAGE",
    "DEFAULT_DATA_PACKAGE",
]
