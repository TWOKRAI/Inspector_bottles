# -*- coding: utf-8 -*-
"""
Модели регистров и данных для App Inspector.

Два типа моделей:
    registers/ — RegisterBase-классы с FieldMeta (регистры + метаданные)
    data/      — BaseModel-классы (контейнеры структурированных данных)
"""
from .registers import (
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
)
from .data import CameraData, RegionData, ChainStepData

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
]
