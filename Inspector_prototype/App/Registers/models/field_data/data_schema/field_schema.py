"""
Единая базовая схема полей для дата-моделей (CameraData, RegionData, ChainStepData).

Подход такой же, как в field_registers/draw.py:
- одна DEFAULT_DATA_FIELD_SCHEMA с общими метаданными;
- field_from_schema = FieldSchema(DEFAULT_DATA_FIELD_SCHEMA);
- конкретные поля описываются прямо в моделях через field_from_schema(...).

Отдельных словарей-схем типа CAMERA_DATA_SCHEMA не используем — источником истины
служат сами Pydantic-модели (как и для *Registers).

DEFAULT_DATA_FIELD_SCHEMA собирается на основе общего каркаса из field_core.base_schema,
чтобы регистры и дата-модели разделяли одинаковую структуру json_schema_extra.
"""
from typing import Any, Dict

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema as FieldSchemaClass
from App.Registers.models.field_core.base_schema import DEFAULT_DATA_FIELD_SCHEMA as CORE_DEFAULT_DATA_FIELD_SCHEMA


DEFAULT_DATA_FIELD_SCHEMA: Dict[str, Any] = CORE_DEFAULT_DATA_FIELD_SCHEMA

# Фабрика полей для дата-моделей: field_from_schema(default, description='...', **overrides)
field_from_schema = FieldSchemaClass(DEFAULT_DATA_FIELD_SCHEMA)


__all__ = ['DEFAULT_DATA_FIELD_SCHEMA', 'field_from_schema']
