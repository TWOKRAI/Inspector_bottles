# -*- coding: utf-8 -*-
"""
PostgreSQLSyncAdapter / PostgreSQLAsyncAdapter — адаптеры для PostgreSQL.

Sync: postgresql+psycopg2://...
Async: postgresql+asyncpg://...
"""
from typing import Any, Dict, Union

from Services.sql.adapters.sync_adapter import BaseSyncAdapter
from Services.sql.adapters.async_adapter import BaseAsyncAdapter
from Services.sql.configs import SQLManagerConfig


class PostgreSQLSyncAdapter(BaseSyncAdapter):
    """Синхронный адаптер для PostgreSQL."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)


class PostgreSQLAsyncAdapter(BaseAsyncAdapter):
    """Асинхронный адаптер для PostgreSQL (asyncpg)."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)
