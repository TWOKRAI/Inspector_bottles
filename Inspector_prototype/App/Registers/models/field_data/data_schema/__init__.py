"""
Схема полей для дата-моделей (как в field_registers/draw.py).

Использование в моделях (camera.py, region.py, chain.py):
  from App.Registers.models.field_data.data_schema import (
      DEFAULT_DATA_FIELD_SCHEMA,
      field_from_schema,
  )
  name: str = field_from_schema('', description='Имя камеры', info='Отображаемое имя камеры')
"""
from App.Registers.models.field_data.data_schema.field_schema import (
    DEFAULT_DATA_FIELD_SCHEMA,
    field_from_schema,
)

__all__ = [
    'DEFAULT_DATA_FIELD_SCHEMA',
    'field_from_schema',
]
