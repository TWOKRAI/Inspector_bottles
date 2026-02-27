from typing import Any, Dict

from App.Registers.models.field_core.base_schema import DEFAULT_REGISTER_FIELD_SCHEMA

"""
Базовая схема метаданных для полей регистров App.

Паттерн использования (см. draw.py и другие *Registers):
- одна DEFAULT_FIELD_SCHEMA с полным набором ключей json_schema_extra;
- field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA) в файлах с регистрами;
- скалярные поля описываются через field_from_schema(default, description=..., info=..., min=..., max=..., ...);
- коллекции (list/dict) задаются через Field(default_factory=..., json_schema_extra={**DEFAULT_FIELD_SCHEMA, ...}).

Сами Pydantic-модели *Registers являются единственным источником истины по полям,
а DEFAULT_FIELD_SCHEMA задаёт только общий «каркас» метаданных.

DEFAULT_FIELD_SCHEMA теперь собирается на базе общего DEFAULT_REGISTER_FIELD_SCHEMA
из модуля field_core.base_schema, чтобы регистры и дата-модели разделяли
одинаковый набор ключей и семантику.
"""

DEFAULT_FIELD_SCHEMA: Dict[str, Any] = DEFAULT_REGISTER_FIELD_SCHEMA

__all__ = ['DEFAULT_FIELD_SCHEMA']
