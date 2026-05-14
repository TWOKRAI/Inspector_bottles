# -*- coding: utf-8 -*-
"""
BaseSyncAdapter — базовая реализация ISyncEngineAdapter.

Общая логика: execute через text(), query с fetchall, connection context.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Union

from sqlalchemy import text
from sqlalchemy.engine import Engine

from Services.sql.configs import SQLManagerConfig
from Services.sql.core.engine_factory import create_sync_engine


class BaseSyncAdapter:
    """Базовая реализация ISyncEngineAdapter."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        self._config = config
        self._engine: Optional[Engine] = None
        self._initialized = False

    @property
    def is_async(self) -> bool:
        return False

    def setup(self) -> bool:
        """Создать engine и проверить подключение."""
        if self._initialized:
            return True
        try:
            self._engine = create_sync_engine(self._config)
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self._initialized = True
            return True
        except Exception:
            self._initialized = False
            raise

    def dispose(self) -> None:
        """Освободить ресурсы пула."""
        if self._engine:
            self._engine.dispose()
            self._engine = None
        self._initialized = False

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Выполнить DML. Возвращает rowcount."""
        if not self._engine:
            raise RuntimeError("Adapter not initialized. Call setup() first.")
        with self._engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            conn.commit()
            return result.rowcount

    def query(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Выполнить SELECT. Возвращает список dict."""
        if not self._engine:
            raise RuntimeError("Adapter not initialized. Call setup() first.")
        with self._engine.connect() as conn:
            result = conn.execute(text(sql), params or {})
            rows = result.fetchall()
            columns = result.keys()
            return [dict(zip(columns, row)) for row in rows]

    @contextmanager
    def connection(self):
        """Контекстный менеджер для транзакций."""
        if not self._engine:
            raise RuntimeError("Adapter not initialized. Call setup() first.")
        with self._engine.connect() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
