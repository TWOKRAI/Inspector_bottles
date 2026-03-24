# -*- coding: utf-8 -*-
"""
SQLiteSyncAdapter / SQLiteAsyncAdapter — адаптеры для SQLite.

Используется для тестов (in-memory) и лёгких сценариев.
"""
from typing import Any, Dict, Union

from sql_module.adapters.sync_adapter import BaseSyncAdapter
from sql_module.adapters.async_adapter import BaseAsyncAdapter
from sql_module.config import SQLManagerConfig


class SQLiteSyncAdapter(BaseSyncAdapter):
    """Синхронный адаптер для SQLite."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)


class SQLiteAsyncAdapter(BaseAsyncAdapter):
    """Асинхронный адаптер для SQLite (aiosqlite)."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)
