# -*- coding: utf-8 -*-
"""
SQLManager — менеджер доступа к БД.

Наследует BaseManager + ObservableMixin.
Интеграция: logger_module (_log_*), error_module (_track_error), statistics_module (_record_timing).
Поддерживает execute, query, uow, get_repository, execute_command.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Type, Union

from base_manager import BaseManager, ObservableMixin

from sql_module.interfaces import (
    IAsyncEngineAdapter,
    IAsyncUnitOfWork,
    IRepository,
    ISchemaMapper,
    ISyncEngineAdapter,
    IUnitOfWork,
)
from sql_module.config import SQLManagerConfig
from sql_module.core.engine_factory import create_async_adapter, create_sync_adapter
from sql_module.core.base_repository import GenericRepository
from sql_module.adapters.schema_mapper import SchemaBaseMapper


class SQLManager(BaseManager, ObservableMixin):
    """SQL-менеджер: execute, query, uow, get_repository, execute_command."""

    def __init__(
        self,
        manager_name: str = "SQLManager",
        config: Optional[Union[SQLManagerConfig, Dict[str, Any]]] = None,
        managers: Optional[Dict[str, Any]] = None,
        process: Optional[Any] = None,
        schema_mapper: Optional[ISchemaMapper] = None,
        **kwargs: Any,
    ):
        BaseManager.__init__(self, manager_name, process=process)
        ObservableMixin.__init__(
            self,
            managers=managers or {},
            config={},
            auto_proxy=True,
            **kwargs,
        )
        self._config = config or {}
        if isinstance(self._config, SQLManagerConfig):
            self._config_dict = self._config.model_dump()
        else:
            self._config_dict = dict(self._config)
        self._adapter: Optional[ISyncEngineAdapter] = None
        self._async_adapter: Optional[IAsyncEngineAdapter] = None
        self._schema_mapper = schema_mapper or SchemaBaseMapper()
        self._repositories: Dict[Type[Any], GenericRepository] = {}

    def initialize(self) -> bool:
        """Создать engine, проверить подключение."""
        if self.is_initialized:
            return True
        try:
            self._adapter = create_sync_adapter(self._config_dict)
            self._adapter.setup()
            self.is_initialized = True
            self._log_info("SQLManager initialized", module="sql_module")
            return True
        except Exception as e:
            self._track_error(e, {"context": "initialize", "module": "sql_module"})
            self._log_error(f"SQLManager init failed: {e}", module="sql_module")
            raise

    def shutdown(self) -> bool:
        """Освободить ресурсы пула."""
        if self._adapter:
            self._adapter.dispose()
            self._adapter = None
        if self._async_adapter:
            self._async_adapter.dispose()
            self._async_adapter = None
        self._repositories.clear()
        self.is_initialized = False
        self._log_info("SQLManager shutdown", module="sql_module")
        return True

    def _ensure_async_adapter(self) -> IAsyncEngineAdapter:
        """Ленивое создание async-адаптера (только при первом вызове uow_async)."""
        if self._async_adapter is None:
            if not self.is_initialized:
                raise RuntimeError("SQLManager not initialized")
            self._async_adapter = create_async_adapter(self._config_dict)
            self._async_adapter.setup()
        return self._async_adapter

    def execute(self, sql: str, params: Optional[Dict[str, Any]] = None) -> int:
        """Выполнить DML."""
        if not self._adapter:
            raise RuntimeError("SQLManager not initialized")
        self.emit_event("db.query.started", {"sql": sql})
        start = time.perf_counter()
        try:
            rows = self._adapter.execute(sql, params or {})
            self._record_timing("db.execute.duration", time.perf_counter() - start, {"op": "execute"})
            self.emit_event("db.query.completed", {"sql": sql, "rows": rows})
            return rows
        except Exception as e:
            self._record_timing("db.execute.duration", time.perf_counter() - start, {"op": "execute", "error": True})
            self._track_error(e, {"context": "execute", "sql": sql[:100], "module": "sql_module"})
            self.emit_event("db.query.failed", {"sql": sql, "error": str(e)})
            raise

    def query(
        self, sql: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Выполнить SELECT."""
        if not self._adapter:
            raise RuntimeError("SQLManager not initialized")
        self.emit_event("db.query.started", {"sql": sql})
        start = time.perf_counter()
        try:
            data = self._adapter.query(sql, params or {})
            self._record_timing("db.query.duration", time.perf_counter() - start, {"op": "query"})
            self.emit_event("db.query.completed", {"sql": sql, "rows": len(data)})
            return data
        except Exception as e:
            self._record_timing("db.query.duration", time.perf_counter() - start, {"op": "query", "error": True})
            self._track_error(e, {"context": "query", "sql": sql[:100], "module": "sql_module"})
            self.emit_event("db.query.failed", {"sql": sql, "error": str(e)})
            raise

    def uow(self) -> IUnitOfWork:
        """Контекстный менеджер для транзакций (sync)."""
        from sql_module.core.unit_of_work import SQLAlchemyUnitOfWork

        if not self._adapter:
            raise RuntimeError("SQLManager not initialized")
        return SQLAlchemyUnitOfWork(self._adapter)

    def uow_async(self) -> IAsyncUnitOfWork:
        """Асинхронный Unit of Work. Адаптер создаётся лениво при первом вызове."""
        from sql_module.core.unit_of_work import AsyncSQLAlchemyUnitOfWork

        adapter = self._ensure_async_adapter()
        return AsyncSQLAlchemyUnitOfWork(adapter)

    def get_repository(
        self,
        schema_class: Type[Any],
        table_name: Optional[str] = None,
    ) -> IRepository[Any, Any]:
        """Получить репозиторий по классу схемы."""
        if schema_class not in self._repositories:
            self._repositories[schema_class] = GenericRepository(
                self._adapter,
                schema_class,
                table_name=table_name,
                schema_mapper=self._schema_mapper,
            )
        return self._repositories[schema_class]

    def _normalize_command(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """Свести команду к плоскому dict для Pydantic-валидации.

        Поддерживает:
        - Прямой: {"command": "db.query", "sql": "...", "params": {}}
        - MessageAdapter: {"command": "db.query", "args": {"sql": "...", "params": {}}}
        """
        args = cmd.get("args", {})
        data = cmd.get("data", {})
        return {**cmd, **args, **data}

    def execute_command(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        """Обработать команду от CommandManager. Dict at Boundary."""
        try:
            cmd_flat = self._normalize_command(cmd)
            command = cmd_flat.get("command")
            if command == "db.query":
                from sql_module.commands import DBQueryCommand

                validated = DBQueryCommand.model_validate(cmd_flat)
                return self._handle_query(validated)
            if command == "db.execute":
                from sql_module.commands import DBExecuteCommand

                validated = DBExecuteCommand.model_validate(cmd_flat)
                return self._handle_execute(validated)
            if command == "db.insert":
                from sql_module.commands import DBInsertCommand

                validated = DBInsertCommand.model_validate(cmd_flat)
                return self._handle_insert(validated)
            return {"status": "error", "reason": f"unknown command: {command}"}
        except Exception as e:
            self._track_error(e, {"context": "execute_command", "module": "sql_module"})
            self._log_error(f"execute_command failed: {e}", module="sql_module")
            return {"status": "error", "reason": str(e)}

    def _handle_query(self, cmd: Any) -> Dict[str, Any]:
        data = self.query(cmd.sql, cmd.params)
        return {"status": "success", "data": data}

    def _handle_execute(self, cmd: Any) -> Dict[str, Any]:
        rows = self.execute(cmd.sql, cmd.params)
        return {"status": "success", "rows": rows}

    def _handle_insert(self, cmd: Any) -> Dict[str, Any]:
        table = cmd.table
        data = cmd.data
        cols = ", ".join(f'"{k}"' for k in data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        sql = f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders})'
        rows = self.execute(sql, data)
        return {"status": "success", "rows": rows}
