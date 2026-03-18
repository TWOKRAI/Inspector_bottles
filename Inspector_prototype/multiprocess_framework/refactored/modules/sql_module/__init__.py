# -*- coding: utf-8 -*-
"""
sql_module — универсальный SQL-менеджер для multiprocess framework.

Поддерживает PostgreSQL, MySQL, SQLite на базе SQLAlchemy 2.0.
Dual sync/async через адаптеры, Unit of Work, fork-safety, typed commands.

Импорты:
    from sql_module import SQLManagerConfig, DBQueryCommand
    from sql_module.interfaces import ISQLManager, IRepository
    from sql_module.commands import DBQueryCommand, DBExecuteCommand
"""
from .config import SQLManagerConfig
from .commands import DBExecuteCommand, DBInsertCommand, DBQueryCommand
from .core import SQLManager, GenericRepository, SQLAlchemyUnitOfWork, AsyncSQLAlchemyUnitOfWork
from .interfaces import (
    IAsyncEngineAdapter,
    IAsyncUnitOfWork,
    IEngineAdapter,
    IMetricsCollector,
    IRepository,
    ISchemaMapper,
    ISQLManager,
    ISyncEngineAdapter,
    IUnitOfWork,
)

__all__ = [
    "SQLManager",
    "GenericRepository",
    "SQLAlchemyUnitOfWork",
    "AsyncSQLAlchemyUnitOfWork",
    "SQLManagerConfig",
    "DBQueryCommand",
    "DBExecuteCommand",
    "DBInsertCommand",
    "ISQLManager",
    "IRepository",
    "IUnitOfWork",
    "IAsyncUnitOfWork",
    "IEngineAdapter",
    "ISyncEngineAdapter",
    "IAsyncEngineAdapter",
    "ISchemaMapper",
    "IMetricsCollector",
]
