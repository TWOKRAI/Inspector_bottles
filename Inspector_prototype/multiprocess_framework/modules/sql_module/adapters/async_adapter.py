# -*- coding: utf-8 -*-
"""
BaseAsyncAdapter — базовая реализация IAsyncEngineAdapter.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool, QueuePool, StaticPool

from sql_module.interfaces import IAsyncEngineAdapter
from sql_module.configs import SQLManagerConfig


def _create_async_engine_from_config(config: Union[SQLManagerConfig, Dict[str, Any]]) -> AsyncEngine:
    """Создать async engine с учётом fork-safety."""
    import os

    cfg = config.model_dump() if isinstance(config, SQLManagerConfig) else dict(config)
    url = cfg.get("url", "sqlite:///:memory:")

    if "sqlite" in url:
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    elif "postgresql" in url and "+" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif "mysql" in url and "+" not in url:
        url = url.replace("mysql://", "mysql+aiomysql://", 1)

    use_null_pool = cfg.get("fork_safe") or os.environ.get("INSPECTOR_MULTIPROCESS", "0") == "1"
    if use_null_pool:
        poolclass = NullPool
    elif ":memory:" in url:
        poolclass = StaticPool
    else:
        poolclass = QueuePool

    engine_kw: Dict[str, Any] = {"pool_pre_ping": cfg.get("pool_pre_ping", True)}
    if poolclass == QueuePool:
        engine_kw["pool_size"] = cfg.get("pool_size", 5)
        engine_kw["max_overflow"] = cfg.get("max_overflow", 10)
        engine_kw["pool_recycle"] = cfg.get("pool_recycle", 3600)

    return create_async_engine(url, poolclass=poolclass, **engine_kw)


class BaseAsyncAdapter:
    """Базовая реализация IAsyncEngineAdapter."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        self._config = config
        self._engine: Optional[AsyncEngine] = None
        self._initialized = False

    @property
    def is_async(self) -> bool:
        return True

    def setup(self) -> bool:
        """Создать engine. Синхронный setup для совместимости."""
        if self._initialized:
            return True
        self._engine = _create_async_engine_from_config(self._config)
        self._initialized = True
        return True

    async def setup_async(self) -> bool:
        """Асинхронная проверка подключения."""
        if not self._engine:
            self.setup()
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True

    def dispose(self) -> None:
        """Освободить ресурсы."""
        if self._engine is not None:
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._engine.dispose())
            except RuntimeError:
                loop = asyncio.new_event_loop()
                try:
                    loop.run_until_complete(self._engine.dispose())
                finally:
                    loop.close()
            self._engine = None
            self._initialized = False

    async def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Выполнить DML."""
        if not self._engine:
            raise RuntimeError("Adapter not initialized")
        async with self._engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            return result.rowcount

    async def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Выполнить SELECT."""
        if not self._engine:
            raise RuntimeError("Adapter not initialized")
        async with self._engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]

    @asynccontextmanager
    async def connection(self):
        """Асинхронный контекстный менеджер для транзакций."""
        if not self._engine:
            raise RuntimeError("Adapter not initialized")
        async with self._engine.connect() as conn:
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise
