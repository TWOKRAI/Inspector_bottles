# -*- coding: utf-8 -*-
"""
Модуль регистров для App Inspector.

Новая архитектура:
- все, что связано с полями регистров и их метаданными — под `models.field_registers`
  (data_schema: DEFAULT_FIELD_SCHEMA; RegisterMetadataHelper — миксин на классах *Registers);
- все, что связано с дата-моделями (CameraData, RegionData, ChainStepData) и их
  упрощёнными схемами — под `models.field_data` (также с подпапкой `data_schema`);
- discovery/регистрация схем и работа с данными — через data_schema_module
  (SchemaManager, register_package_registers, registers_io).

Специальный толстый фасад RegistersManager больше не нужен: логика разнесена
по слоям (SchemaManager, FieldSchema, helper-ы), а регистры можно регистрировать
напрямую через data_schema_module.
"""

from .models import (
    CameraRegisters,
    ProcessingRegisters,
    PostProcessingRegisters,
    VisualRegisters,
    DrawRegisters,
    RobotRegisters,
    ConveyorRegisters,
    NeurounRegisters,
    HikvisionRegisters,
    FrameProcessRegisters,
)
from .models.field_data import (
    CameraData,
    RegionData,
    ChainStepData,
    DEFAULT_DATA_FIELD_SCHEMA,
    field_from_schema as data_field_from_schema,
)
from .models.field_registers import (
    FieldSchema,
    DEFAULT_FIELD_SCHEMA as DEFAULT_REGISTER_FIELD_SCHEMA,
    RegisterMetadataHelper,
)
from .manager import RegistersManager

__all__ = [
    # Модели регистров управления
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
    # Модели данных
    'CameraData',
    'RegionData',
    'ChainStepData',
    # Общая инфраструктура полей регистров
    'FieldSchema',
    'DEFAULT_REGISTER_FIELD_SCHEMA',
    'RegisterMetadataHelper',
    # Схема полей дата-моделей (единая, как в field_registers)
    'DEFAULT_DATA_FIELD_SCHEMA',
    'data_field_from_schema',
    'RegistersManager',
]
