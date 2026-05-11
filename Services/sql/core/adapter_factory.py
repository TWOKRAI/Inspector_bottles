# -*- coding: utf-8 -*-
"""AdapterFactory — выбор конкретного {Sync,Async}EngineAdapter по dialect.

Выделен из engine_factory.py, чтобы разорвать цикл импорта:
    sync_adapter.py → engine_factory.py → {sqlite,postgresql,mysql}.py → sync_adapter.py

Теперь engine_factory.py отвечает только за SQLAlchemy Engine,
а выбор диалекта живёт здесь и импортируется только из sql_manager.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Union

from Services.sql.configs import SQLManagerConfig
from Services.sql.interfaces import IAsyncEngineAdapter, ISyncEngineAdapter


def _resolve_dialect(
    config: Union[SQLManagerConfig, Dict[str, Any]],
    dialect: Optional[str],
) -> str:
    if dialect:
        return dialect
    if isinstance(config, dict):
        return config.get("dialect", "sqlite")
    return getattr(config, "dialect", "sqlite")


def create_sync_adapter(
    config: Union[SQLManagerConfig, Dict[str, Any]],
    dialect: Optional[str] = None,
) -> ISyncEngineAdapter:
    """Создать ISyncEngineAdapter по конфигу.

    Args:
        config: SQLManagerConfig или dict
        dialect: Переопределить dialect из конфига (postgresql, mysql, sqlite)
    """
    d = _resolve_dialect(config, dialect)

    if d == "sqlite":
        from Services.sql.adapters.sqlite import SQLiteSyncAdapter

        return SQLiteSyncAdapter(config)
    if d in ("postgresql", "postgres"):
        from Services.sql.adapters.postgresql import PostgreSQLSyncAdapter

        return PostgreSQLSyncAdapter(config)
    if d == "mysql":
        from Services.sql.adapters.mysql import MySQLSyncAdapter

        return MySQLSyncAdapter(config)

    raise ValueError(f"Unknown dialect: {d}. Supported: sqlite, postgresql, mysql")


def create_async_adapter(
    config: Union[SQLManagerConfig, Dict[str, Any]],
    dialect: Optional[str] = None,
) -> IAsyncEngineAdapter:
    """Создать IAsyncEngineAdapter по конфигу."""
    d = _resolve_dialect(config, dialect)

    if d == "sqlite":
        from Services.sql.adapters.sqlite import SQLiteAsyncAdapter

        return SQLiteAsyncAdapter(config)
    if d in ("postgresql", "postgres"):
        from Services.sql.adapters.postgresql import PostgreSQLAsyncAdapter

        return PostgreSQLAsyncAdapter(config)
    if d == "mysql":
        from Services.sql.adapters.mysql import MySQLAsyncAdapter

        return MySQLAsyncAdapter(config)

    raise ValueError(f"Unknown dialect: {d}. Supported: sqlite, postgresql, mysql")
