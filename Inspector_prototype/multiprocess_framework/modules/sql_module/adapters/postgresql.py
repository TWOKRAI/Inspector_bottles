# -*- coding: utf-8 -*-
"""
PostgreSQLSyncAdapter / PostgreSQLAsyncAdapter — адаптеры для PostgreSQL.

Sync: postgresql+psycopg2://...
Async: postgresql+asyncpg://...
"""
from typing import Any, Dict, Union

from multiprocess_framework.modules.sql_module.adapters.sync_adapter import BaseSyncAdapter
from multiprocess_framework.modules.sql_module.adapters.async_adapter import BaseAsyncAdapter
from multiprocess_framework.modules.sql_module.configs import SQLManagerConfig


class PostgreSQLSyncAdapter(BaseSyncAdapter):
    """Синхронный адаптер для PostgreSQL."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)


class PostgreSQLAsyncAdapter(BaseAsyncAdapter):
    """Асинхронный адаптер для PostgreSQL (asyncpg)."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)
