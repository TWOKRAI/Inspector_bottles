# -*- coding: utf-8 -*-
"""
Модели регистров для App Inspector.

Все модели *Registers и инфраструктура схем находятся в подпакете field_registers.
Здесь — реэкспорт для обратной совместимости и для discovery по пакету App.Registers.models.
"""
from App.Registers.models.field_registers import (
    FieldSchema,
    DEFAULT_FIELD_SCHEMA,
    RegisterMetadataHelper,
    DrawRegisters,
    CameraRegisters,
    ProcessingRegisters,
    PostProcessingRegisters,
    VisualRegisters,
    RobotRegisters,
    ConveyorRegisters,
    NeurounRegisters,
    HikvisionRegisters,
    FrameProcessRegisters,
)

__all__ = [
    'FieldSchema',
    'DEFAULT_FIELD_SCHEMA',
    'RegisterMetadataHelper',
    'CameraRegisters',
    'ProcessingRegisters',
    'PostProcessingRegisters',
    'VisualRegisters',
    'DrawRegisters',
    'RobotRegisters',
    'ConveyorRegisters',
    'NeurounRegisters',
    'HikvisionRegisters',
    'FrameProcessRegisters',
]
