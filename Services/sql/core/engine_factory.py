# -*- coding: utf-8 -*-
"""
EngineFactory — создание Engine/SyncAdapter с учётом fork-safety.

В multiprocess QueuePool не fork-safe — deadlocks при SSL/PostgreSQL.
Используем NullPool при INSPECTOR_MULTIPROCESS=1 или config.fork_safe=True.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Union

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

from Services.sql.interfaces import ISyncEngineAdapter
from Services.sql.configs import SQLManagerConfig


def _should_use_null_pool(config: Union[SQLManagerConfig, Dict[str, Any]]) -> bool:
    """Определить, нужен ли NullPool (fork-safe)."""
    if isinstance(config, dict):
        if config.get("fork_safe"):
            return True
    else:
        if config.fork_safe:
            return True
    return os.environ.get("INSPECTOR_MULTIPROCESS", "0") == "1"


def _config_to_dict(config: Union[SQLManagerConfig, Dict[str, Any]]) -> Dict[str, Any]:
    """Нормализовать конфиг в dict (Dict at Boundary)."""
    if isinstance(config, dict):
        return config
    return config.model_dump()


def create_sync_engine(
    config: Union[SQLManagerConfig, Dict[str, Any]],
) -> Engine:
    """Создать синхронный SQLAlchemy Engine с учётом fork-safety.

    Args:
        config: SQLManagerConfig или dict с url, pool_size, и т.д.

    Returns:
        SQLAlchemy Engine
    """
    cfg = _config_to_dict(config)
    url = cfg.get("url", "sqlite:///:memory:")
    use_null_pool = _should_use_null_pool(config)

    if use_null_pool:
        poolclass = NullPool
    elif ":memory:" in url or "file::memory:" in url:
        poolclass = StaticPool
    else:
        poolclass = QueuePool

    engine_kw: Dict[str, Any] = {
        "pool_pre_ping": cfg.get("pool_pre_ping", True),
    }
    if poolclass == QueuePool:
        engine_kw["pool_size"] = cfg.get("pool_size", 5)
        engine_kw["max_overflow"] = cfg.get("max_overflow", 10)
        engine_kw["pool_recycle"] = cfg.get("pool_recycle", 3600)
    elif poolclass == NullPool:
        pass

    return create_engine(
        url,
        poolclass=poolclass,
        **engine_kw,
    )


def create_sync_adapter(
    config: Union[SQLManagerConfig, Dict[str, Any]],
    dialect: Optional[str] = None,
) -> ISyncEngineAdapter:
    """Создать ISyncEngineAdapter по конфигу.

    Args:
        config: SQLManagerConfig или dict
        dialect: Переопределить dialect из конфига (postgresql, mysql, sqlite)

    Returns:
        Реализация ISyncEngineAdapter для указанного dialect
    """
    cfg = _config_to_dict(config)
    d = dialect or cfg.get("dialect", "sqlite")

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
) -> "IAsyncEngineAdapter":
    """Создать IAsyncEngineAdapter по конфигу."""
    from Services.sql.interfaces import IAsyncEngineAdapter

    cfg = _config_to_dict(config)
    d = dialect or cfg.get("dialect", "sqlite")

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
