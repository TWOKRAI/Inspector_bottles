# -*- coding: utf-8 -*-
"""
MySQLSyncAdapter / MySQLAsyncAdapter — адаптеры для MySQL.

Sync: mysql+pymysql://...
Async: mysql+aiomysql://...
"""
from typing import Any, Dict, Union

from Services.sql.adapters.sync_adapter import BaseSyncAdapter
from Services.sql.adapters.async_adapter import BaseAsyncAdapter
from Services.sql.configs import SQLManagerConfig


class MySQLSyncAdapter(BaseSyncAdapter):
    """Синхронный адаптер для MySQL."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)


class MySQLAsyncAdapter(BaseAsyncAdapter):
    """Асинхронный адаптер для MySQL (aiomysql)."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)
