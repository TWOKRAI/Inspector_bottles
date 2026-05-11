# -*- coding: utf-8 -*-
"""
SchemaBaseMapper -- ISchemaMapper implementation for SchemaBase / Pydantic v2.

Maps Python types to SQLAlchemy column types, reads FieldMeta annotations
and SQLMeta nested class for rich table metadata.

entity_to_row / row_to_entity via model_dump / model_validate.
"""
from __future__ import annotations

import datetime
from typing import Any, Dict, Type, get_origin, get_args

from pydantic_core import PydanticUndefined
from sqlalchemy import Integer, String, Float, Boolean, DateTime, Date
from sqlalchemy.sql.sqltypes import TypeEngine

from Services.sql.interfaces import ISchemaMapper
from Services.sql.adapters.sql_meta import extract_sql_meta

try:
    from multiprocess_framework.modules.data_schema_module import FieldMeta
except ImportError:
    try:
        from multiprocess_framework.modules.data_schema_module import FieldMeta
    except ImportError:
        FieldMeta = None  # type: ignore[misc,assignment]


_TYPE_MAP: Dict[type, Type[TypeEngine]] = {
    int: Integer,
    str: String,
    float: Float,
    bool: Boolean,
    datetime.datetime: DateTime,
    datetime.date: Date,
}


def _python_type_to_sqlalchemy(python_type: type) -> TypeEngine | Type[TypeEngine]:
    """Map a Python type to an SQLAlchemy column type."""
    sa_type = _TYPE_MAP.get(python_type)
    if sa_type is not None:
        return sa_type
    return String


def _get_annotation_type(ann: Any) -> type:
    """Extract the base type from Optional[X], Union[X, None], or Annotated[X, ...]."""
    if ann is None:
        return str

    # Unwrap Annotated[T, ...] first
    origin = get_origin(ann)
    if origin is not None:
        # typing.Annotated has __metadata__ attribute
        if hasattr(ann, "__metadata__"):
            inner = get_args(ann)[0]
            return _get_annotation_type(inner)

    args = get_args(ann)
    if args:
        for a in args:
            if a is not type(None) and isinstance(a, type):
                return a
    return ann if isinstance(ann, type) else str


def _is_optional(ann: Any) -> bool:
    """Check if annotation is Optional[T] (Union[T, None])."""
    # Unwrap Annotated first
    if hasattr(ann, "__metadata__"):
        ann = get_args(ann)[0]

    args = get_args(ann)
    if args and type(None) in args:
        return True
    return False


def _find_field_meta(field_info: Any) -> Any | None:
    """Find FieldMeta instance in field_info.metadata list."""
    if FieldMeta is None:
        return None
    metadata = getattr(field_info, "metadata", None)
    if not metadata:
        return None
    for item in metadata:
        if isinstance(item, FieldMeta):
            return item
    return None


class SchemaBaseMapper:
    """ISchemaMapper implementation for SchemaBase and Pydantic BaseModel.

    Reads FieldMeta annotations for check constraints, string lengths,
    readonly flags. Reads SQLMeta nested class for table name, indexes,
    unique constraints.
    """

    def schema_to_table_meta(self, schema_class: Type[Any]) -> Dict[str, Any]:
        """Convert a schema class to table metadata dict.

        Returns dict with keys:
            table_name, columns, primary_key, indexes, unique_together

        Backward compatible: consumers reading only table_name, columns[x]["type"],
        columns[x]["nullable"], primary_key continue to work unchanged.
        """
        # --- SQLMeta: table_name, indexes, unique_together ---
        sql_meta = extract_sql_meta(schema_class)
        table_name = sql_meta["table_name"]
        indexes = sql_meta["indexes"]
        unique_together = sql_meta["unique_together"]

        columns: Dict[str, Any] = {}
        primary_key: list[str] = []

        if hasattr(schema_class, "model_fields"):
            for field_name, field_info in schema_class.model_fields.items():
                ann = field_info.annotation
                base_type = _get_annotation_type(ann)
                col_type = _python_type_to_sqlalchemy(base_type)

                # Nullable: not required OR Optional[T]
                nullable = (not field_info.is_required()) or _is_optional(ann)

                col_meta: Dict[str, Any] = {
                    "type": col_type,
                    "nullable": nullable,
                    "check_min": None,
                    "check_max": None,
                    "default": None,
                    "readonly": False,
                }

                # --- FieldMeta enrichment ---
                meta = _find_field_meta(field_info)
                if meta is not None:
                    # Numeric constraints
                    if base_type in (int, float):
                        if meta.min is not None:
                            col_meta["check_min"] = meta.min
                        if meta.max is not None:
                            col_meta["check_max"] = meta.max

                    # String length from meta.max
                    if base_type is str and meta.max is not None:
                        col_meta["type"] = String(int(meta.max))

                    col_meta["readonly"] = meta.readonly

                # --- Default value ---
                default = field_info.default
                if default is not PydanticUndefined and default is not None:
                    col_meta["default"] = default

                columns[field_name] = col_meta

                if field_name == "id":
                    primary_key.append(field_name)

        if not primary_key and columns:
            primary_key = [list(columns.keys())[0]]

        return {
            "table_name": table_name,
            "columns": columns,
            "primary_key": primary_key,
            "indexes": indexes,
            "unique_together": unique_together,
        }

    def row_to_entity(self, row: Dict[str, Any], schema_class: Type[Any]) -> Any:
        """Convert a DB row dict to a schema entity."""
        return schema_class.model_validate(row)

    def entity_to_row(self, entity: Any) -> Dict[str, Any]:
        """Convert a schema entity to a dict for INSERT/UPDATE."""
        return entity.model_dump()
