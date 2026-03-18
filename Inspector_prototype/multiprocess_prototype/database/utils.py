# multiprocess_prototype\database\utils.py
"""Утилиты для работы с БД: создание таблиц из схемы."""
from typing import Any, Dict, Type


_SQLITE_TYPE_MAP = {
    "Integer": "INTEGER",
    "Float": "REAL",
    "String": "TEXT",
    "Boolean": "INTEGER",
    "DateTime": "TEXT",
}


def build_create_table_sql(
    schema_class: Type[Any],
    schema_mapper: Any,
    if_not_exists: bool = True,
) -> str:
    """
    Построить CREATE TABLE для SQLite из схемы data_schema_module.

    Args:
        schema_class: Класс схемы (DetectionSchema и т.п.)
        schema_mapper: ISchemaMapper (SchemaBaseMapper)
        if_not_exists: Добавить IF NOT EXISTS

    Returns:
        SQL-строка CREATE TABLE
    """
    meta = schema_mapper.schema_to_table_meta(schema_class)
    table_name = meta["table_name"]
    columns = meta.get("columns", {})
    primary_key = meta.get("primary_key", [])

    parts = []
    for col_name, col_info in columns.items():
        is_pk_auto = col_name == "id" and "id" in primary_key
        if is_pk_auto:
            parts.append(f'  "{col_name}" INTEGER PRIMARY KEY AUTOINCREMENT')
            continue
        sa_type = col_info.get("type")
        type_name = getattr(sa_type, "__name__", "String") if sa_type else "String"
        sql_type = _SQLITE_TYPE_MAP.get(type_name, "TEXT")
        nullable = "" if col_info.get("nullable", True) else " NOT NULL"
        parts.append(f'  "{col_name}" {sql_type}{nullable}')

    if_not_exists_clause = " IF NOT EXISTS" if if_not_exists else ""
    return f'CREATE TABLE{if_not_exists_clause} "{table_name}" (\n' + ",\n".join(parts) + "\n)"
