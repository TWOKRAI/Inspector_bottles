# -*- coding: utf-8 -*-
"""
SQLMeta — декларативные метаданные таблицы для подклассов SchemaBase.

Usage::

    class UserSchema(SchemaBase):
        class SQLMeta:
            table_name = "users"
            indexes = [("email",)]
            unique_together = [("email",)]

        id: int | None = None
        name: str = ""

Pydantic v2 игнорирует вложенные классы, поэтому SQLMeta не влияет на
serialization или model_fields.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple, Type


class SQLMeta:
    """Namespace class for SQL table metadata.

    Used as a nested class inside SchemaBase subclasses.
    Pydantic ignores nested classes, so this has no impact on serialization.

    Attributes:
        table_name:       explicit table name (overrides auto-derive)
        indexes:          list of column tuples for CREATE INDEX
        unique_together:  list of column tuples for UNIQUE constraints
    """

    table_name: str = ""
    indexes: tuple = ()
    unique_together: tuple = ()


def _derive_table_name(class_name: str) -> str:
    """Derive table name from class name.

    Rules:
        1. Strip 'Schema' suffix (case-sensitive)
        2. Lowercase
        3. Pluralize: 's' → 'ses', 'x'/'z'/'ch'/'sh' → +'es', 'y' → 'ies', else +'s'

    Examples:
        UserSchema  -> users
        OrderItem   -> orderitems
        Address     -> addresses
        Schema      -> schemas
        Category    -> categories
        Box         -> boxes
    """
    name = class_name
    if name.endswith("Schema") and len(name) > len("Schema"):
        name = name[: -len("Schema")]
    name = name.lower()
    if name.endswith("s") or name.endswith("sh") or name.endswith("ch"):
        return name + "es"
    if name.endswith("x") or name.endswith("z"):
        return name + "es"
    if name.endswith("y") and len(name) > 1 and name[-2] not in "aeiou":
        return name[:-1] + "ies"
    return name + "s"


def extract_sql_meta(schema_class: Type[Any]) -> Dict[str, Any]:
    """Extract SQL metadata from a SchemaBase subclass.

    If ``schema_class`` has a nested ``SQLMeta`` class, reads
    ``table_name``, ``indexes``, ``unique_together`` from it.
    Otherwise (or if ``table_name`` is empty), derives table_name
    from the class name via :func:`_derive_table_name`.

    Returns:
        ``{"table_name": str, "indexes": list, "unique_together": list}``
    """
    meta = getattr(schema_class, "SQLMeta", None)

    if meta is not None:
        table_name = getattr(meta, "table_name", "") or ""
        indexes = list(getattr(meta, "indexes", []))
        unique_together = list(getattr(meta, "unique_together", []))
    else:
        table_name = ""
        indexes = []
        unique_together = []

    if not table_name:
        table_name = _derive_table_name(schema_class.__name__)

    return {
        "table_name": table_name,
        "indexes": indexes,
        "unique_together": unique_together,
    }
