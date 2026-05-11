# -*- coding: utf-8 -*-
"""
EngineFactory — создание SQLAlchemy Engine с учётом fork-safety.

В multiprocess QueuePool не fork-safe — deadlocks при SSL/PostgreSQL.
Используем NullPool при INSPECTOR_MULTIPROCESS=1 или config.fork_safe=True.

Выбор конкретного адаптера по dialect живёт в adapter_factory.py —
разделение нужно, чтобы sync_adapter мог зависеть только от builder'а Engine,
не подтягивая конкретные подклассы (sqlite/postgresql/mysql).
"""
from __future__ import annotations

import os
from typing import Any, Dict, Union

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

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

    # Дополнительные аргументы для DBAPI connect() — например,
    # {"check_same_thread": False} для SQLite в многопоточных приложениях.
    connect_args = cfg.get("connect_args") or {}
    if connect_args:
        engine_kw["connect_args"] = connect_args

    return create_engine(
        url,
        poolclass=poolclass,
        **engine_kw,
    )
