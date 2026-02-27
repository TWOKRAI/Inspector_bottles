# -*- coding: utf-8 -*-
"""
Дата-модели приложения: CameraData (основной тип), RegionData и ChainStepData (вспомогательные).
Поля заданы через единую схему field_data.data_schema (DEFAULT_DATA_FIELD_SCHEMA + field_from_schema),
по тому же принципу, что и регистры в field_registers/draw.py.

Импорт моделей:
  from App.Registers.models.field_data import CameraData, RegionData, ChainStepData

Импорт схемы и фабрики полей:
  from App.Registers.models.field_data import DEFAULT_DATA_FIELD_SCHEMA, field_from_schema
"""
from App.Registers.models.field_data.camera import CameraData
from App.Registers.models.field_data.region import RegionData
from App.Registers.models.field_data.chain import ChainStepData

from App.Registers.models.field_data.data_schema import (
    DEFAULT_DATA_FIELD_SCHEMA,
    field_from_schema,
)

__all__ = [
    'CameraData',
    'RegionData',
    'ChainStepData',
    'DEFAULT_DATA_FIELD_SCHEMA',
    'field_from_schema',
]
