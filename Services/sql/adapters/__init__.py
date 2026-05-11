"""Адаптеры sql_module — barrel-export.

Публичный API подмодуля. Внешние компоненты импортируют адаптеры через
`from Services.sql.adapters import …`, не обращаясь к внутренним файлам
(`mysql.py` / `postgresql.py` / `sqlite.py` / `sync_adapter.py` /
`async_adapter.py` / `schema_mapper.py` / `sql_meta.py`).

Доступно:
- Базовые адаптеры: `BaseSyncAdapter`, `BaseAsyncAdapter`.
- Sync-реализации: `SQLiteSyncAdapter`, `PostgreSQLSyncAdapter`, `MySQLSyncAdapter`.
- Async-реализации: `SQLiteAsyncAdapter`, `PostgreSQLAsyncAdapter`, `MySQLAsyncAdapter`.
- Mapper и метаданные: `SchemaBaseMapper`, `SQLMeta`, `extract_sql_meta`.
"""
from .async_adapter import BaseAsyncAdapter
from .mysql import MySQLAsyncAdapter, MySQLSyncAdapter
from .postgresql import PostgreSQLAsyncAdapter, PostgreSQLSyncAdapter
from .schema_mapper import SchemaBaseMapper
from .sql_meta import SQLMeta, extract_sql_meta
from .sqlite import SQLiteAsyncAdapter, SQLiteSyncAdapter
from .sync_adapter import BaseSyncAdapter

__all__ = [
    # Базовые
    "BaseSyncAdapter",
    "BaseAsyncAdapter",
    # Sync-реализации
    "SQLiteSyncAdapter",
    "PostgreSQLSyncAdapter",
    "MySQLSyncAdapter",
    # Async-реализации
    "SQLiteAsyncAdapter",
    "PostgreSQLAsyncAdapter",
    "MySQLAsyncAdapter",
    # Mapper и метаданные
    "SchemaBaseMapper",
    "SQLMeta",
    "extract_sql_meta",
]
