# multiprocess_prototype\database\utils.py
"""Утилиты для работы с БД: создание таблиц из схемы, экспорт."""
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from multiprocess_framework.refactored.modules.sql_module.export import (
    TableExporter,
    ExportFormat,
)


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


def _ts_fmt(v: Any) -> str:
    if v is None:
        return ""
    try:
        return datetime.fromtimestamp(float(v)).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    except (ValueError, OSError, TypeError):
        return str(v)


def create_detection_exporter() -> TableExporter:
    """TableExporter, настроенный для схемы детекций (читаемый формат)."""
    return TableExporter(
        columns=["id", "timestamp", "frame_name", "frame_id", "x1", "y1", "x2", "y2", "center_x", "center_y", "area"],
        readable_blocks=[
            ("ID", lambda r: str(r.get("id", ""))),
            ("Время", lambda r: _ts_fmt(r.get("timestamp"))),
            ("Кадр", lambda r: f"{r.get('frame_name', '')} (id={r.get('frame_id', '')})"),
            ("Bbox", lambda r: f"({r.get('x1')}, {r.get('y1')}) - ({r.get('x2')}, {r.get('y2')})"),
            ("Центр", lambda r: f"({r.get('center_x')}, {r.get('center_y')})"),
            ("Площадь", lambda r: f"{r.get('area', '')} px"),
        ],
    )


def read_from_sqlite(
    db_path: Path,
    table: str = "detections",
    order_by: str = "id",
    offset: int = 0,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Прочитать строки из SQLite (для standalone-скриптов без SQLManager).

    Returns:
        List[Dict] — строки
    """
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sql = f'SELECT * FROM "{table}" ORDER BY "{order_by}"'
    params = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    if offset > 0:
        sql += " OFFSET ?"
        params.append(offset)
    cur = conn.execute(sql, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows
