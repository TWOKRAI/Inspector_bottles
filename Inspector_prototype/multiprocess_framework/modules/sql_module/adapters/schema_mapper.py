# -*- coding: utf-8 -*-
"""
SchemaBaseMapper — реализация ISchemaMapper для SchemaBase/Pydantic.

Маппинг Python типов -> SQLAlchemy типы для создания таблиц.
entity_to_row / row_to_entity через model_dump / model_validate.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Type, get_origin, get_args

from sqlalchemy import Integer, String, Float, Boolean, DateTime
from sqlalchemy.sql.sqltypes import TypeEngine

from sql_module.interfaces import ISchemaMapper


_TYPE_MAP: Dict[type, Type[TypeEngine]] = {
    int: Integer,
    str: String,
    float: Float,
    bool: Boolean,
}


def _python_type_to_sqlalchemy(python_type: type) -> Type[TypeEngine]:
    """Маппинг Python типа в SQLAlchemy тип."""
    if python_type in _TYPE_MAP:
        return _TYPE_MAP[python_type]
    if python_type == datetime.datetime:
        return DateTime
    return String


def _get_annotation_type(ann: Any) -> type:
    """Извлечь тип из Optional[X] или Union[X, None]."""
    if ann is None:
        return str
    args = get_args(ann)
    if args:
        for a in args:
            if a is not type(None) and isinstance(a, type):
                return a
    return ann if isinstance(ann, type) else str


class SchemaBaseMapper:
    """Реализация ISchemaMapper для SchemaBase и Pydantic BaseModel."""

    def schema_to_table_meta(self, schema_class: Type[Any]) -> Dict[str, Any]:
        """Преобразовать класс схемы в метаданные таблицы.

        Returns:
            dict с ключами: table_name, columns, primary_key
        """
        table_name = schema_class.__name__.lower()
        if table_name.endswith("schema"):
            table_name = table_name[:-6] + "s"
        elif table_name.endswith("config"):
            table_name = table_name + "s"

        columns: Dict[str, Any] = {}
        primary_key: list[str] = []

        if hasattr(schema_class, "model_fields"):
            for field_name, field_info in schema_class.model_fields.items():
                ann = field_info.annotation
                inner_type = _get_annotation_type(ann)
                col_type = _python_type_to_sqlalchemy(inner_type)
                nullable = field_info.is_required() is False
                columns[field_name] = {"type": col_type, "nullable": nullable}
                if field_name == "id":
                    primary_key.append(field_name)

        if not primary_key and columns:
            primary_key = [list(columns.keys())[0]]

        return {
            "table_name": table_name,
            "columns": columns,
            "primary_key": primary_key,
        }

    def row_to_entity(self, row: Dict[str, Any], schema_class: Type[Any]) -> Any:
        """Преобразовать строку БД в сущность."""
        return schema_class.model_validate(row)

    def entity_to_row(self, entity: Any) -> Dict[str, Any]:
        """Преобразовать сущность в словарь для INSERT/UPDATE."""
        return entity.model_dump()
