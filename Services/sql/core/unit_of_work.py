# -*- coding: utf-8 -*-
"""
SQLAlchemyUnitOfWork / AsyncSQLAlchemyUnitOfWork — Unit of Work для транзакций.

Sync и async варианты. connection() — единая точка для выполнения SQL в транзакции.
"""
from __future__ import annotations

from typing import Any, Dict, Type

from Services.sql.interfaces import (
    IAsyncEngineAdapter,
    IAsyncUnitOfWork,
    ISyncEngineAdapter,
    IUnitOfWork,
)


class SQLAlchemyUnitOfWork:
    """Синхронный Unit of Work с connection context."""

    def __init__(self, adapter: ISyncEngineAdapter):
        self._adapter = adapter
        self._repos: Dict[Type[Any], Any] = {}

    def __enter__(self) -> IUnitOfWork:
        return self

    def __exit__(self, *args: Any) -> None:
        pass

    def commit(self) -> None:
        """Commit выполняется при выходе из connection() context."""
        pass

    def rollback(self) -> None:
        """Rollback — при исключении в connection() context."""
        pass

    def connection(self):
        """Контекстный менеджер для транзакций."""
        return self._adapter.connection()


class AsyncSQLAlchemyUnitOfWork:
    """Асинхронный Unit of Work. Лёгкий, без лишних аллокаций."""

    def __init__(self, adapter: IAsyncEngineAdapter):
        self._adapter = adapter
        self._repos: Dict[Type[Any], Any] = {}

    async def __aenter__(self) -> IAsyncUnitOfWork:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def commit(self) -> None:
        """Commit выполняется при выходе из connection() context."""
        pass

    async def rollback(self) -> None:
        """Rollback — при исключении в connection() context."""
        pass

    def connection(self):
        """Асинхронный контекстный менеджер для транзакций."""
        return self._adapter.connection()
