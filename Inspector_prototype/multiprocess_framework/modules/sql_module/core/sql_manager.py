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

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin

from multiprocess_framework.modules.sql_module.interfaces import (
    IAsyncEngineAdapter,
    IAsyncUnitOfWork,
    IRepository,
    ISchemaMapper,
    ISyncEngineAdapter,
    IUnitOfWork,
)
from multiprocess_framework.modules.sql_module.configs import SQLManagerConfig
from multiprocess_framework.modules.sql_module.core.engine_factory import create_async_adapter, create_sync_adapter
from multiprocess_framework.modules.sql_module.core.base_repository import GenericRepository
from multiprocess_framework.modules.sql_module.core.ddl_builder import DDLBuilder
from multiprocess_framework.modules.sql_module.core.queryset import AsyncQuerySet, QuerySet
from multiprocess_framework.modules.sql_module.adapters.schema_mapper import SchemaBaseMapper


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
        start = time.perf_counter()
        try:
            rows = self._adapter.execute(sql, params or {})
            self._record_timing("db.execute.duration", time.perf_counter() - start, {"op": "execute"})
            return rows
        except Exception as e:
            self._record_timing("db.execute.duration", time.perf_counter() - start, {"op": "execute", "error": True})
            self._track_error(e, {"context": "execute", "sql": sql[:100], "module": "sql_module"})
            raise

    def query(
        self, sql: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Выполнить SELECT."""
        if not self._adapter:
            raise RuntimeError("SQLManager not initialized")
        start = time.perf_counter()
        try:
            data = self._adapter.query(sql, params or {})
            self._record_timing("db.query.duration", time.perf_counter() - start, {"op": "query"})
            return data
        except Exception as e:
            self._record_timing("db.query.duration", time.perf_counter() - start, {"op": "query", "error": True})
            self._track_error(e, {"context": "query", "sql": sql[:100], "module": "sql_module"})
            raise

    def query_range(
        self,
        table: str,
        order_by: str = "id",
        offset: int = 0,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Выборка диапазона строк из таблицы.

        Args:
            table: Имя таблицы
            order_by: Колонка для сортировки
            offset: Смещение (начало диапазона)
            limit: Макс. количество строк. None — все с offset до конца.

        Returns:
            List[Dict] — строки
        """
        self._validate_identifier(table)
        self._validate_identifier(order_by)
        sql = f'SELECT * FROM "{table}" ORDER BY "{order_by}"'
        params: Dict[str, Any] = {}
        if limit is not None:
            sql += " LIMIT :limit"
            params["limit"] = limit
        if offset > 0:
            sql += " OFFSET :offset"
            params["offset"] = offset
        return self.query(sql, params if params else None)

    def uow(self) -> IUnitOfWork:
        """Контекстный менеджер для транзакций (sync)."""
        from multiprocess_framework.modules.sql_module.core.unit_of_work import SQLAlchemyUnitOfWork

        if not self._adapter:
            raise RuntimeError("SQLManager not initialized")
        return SQLAlchemyUnitOfWork(self._adapter)

    def uow_async(self) -> IAsyncUnitOfWork:
        """Асинхронный Unit of Work. Адаптер создаётся лениво при первом вызове."""
        from multiprocess_framework.modules.sql_module.core.unit_of_work import AsyncSQLAlchemyUnitOfWork

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

    def create_tables(
        self,
        schema_classes: list,
        dialect: Optional[str] = None,
    ) -> int:
        """Автоматически создать таблицы из SchemaBase-классов.

        Args:
            schema_classes: Список SchemaBase-подклассов
            dialect: SQL-диалект (auto-detect из конфига если None)
        Returns:
            Количество выполненных DDL-операторов
        """
        if not self._adapter:
            raise RuntimeError("SQLManager not initialized")
        if dialect is None:
            dialect = self._config_dict.get("dialect", "sqlite")
        builder = DDLBuilder(self._schema_mapper)
        statements = builder.build_create_all(schema_classes, dialect)
        for stmt in statements:
            self.execute(stmt)
        self._log_info(
            f"Created {len(schema_classes)} table(s) ({len(statements)} statements)",
            module="sql_module",
        )
        return len(statements)

    def objects(
        self,
        schema_class: Type[Any],
        table_name: Optional[str] = None,
    ) -> QuerySet:
        """Получить QuerySet для Django-style chained queries.

        Args:
            schema_class: SchemaBase-подкласс
            table_name: Переопределить имя таблицы (auto-detect из SQLMeta если None)
        Returns:
            QuerySet instance
        """
        if table_name is None:
            meta = self._schema_mapper.schema_to_table_meta(schema_class)
            table_name = meta["table_name"]
        return QuerySet(self._adapter, schema_class, self._schema_mapper, table_name)

    def objects_async(
        self,
        schema_class: Type[Any],
        table_name: Optional[str] = None,
    ) -> AsyncQuerySet:
        """Получить AsyncQuerySet для async chained queries.

        Args:
            schema_class: SchemaBase-подкласс
            table_name: Переопределить имя таблицы (auto-detect из SQLMeta если None)
        Returns:
            AsyncQuerySet instance
        """
        adapter = self._ensure_async_adapter()
        if table_name is None:
            meta = self._schema_mapper.schema_to_table_meta(schema_class)
            table_name = meta["table_name"]
        return AsyncQuerySet(adapter, schema_class, self._schema_mapper, table_name)

    @staticmethod
    def _validate_identifier(name: str) -> str:
        import re
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
            raise ValueError(f"Invalid SQL identifier: {name!r}")
        return name

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
                from multiprocess_framework.modules.sql_module.commands import DBQueryCommand

                validated = DBQueryCommand.model_validate(cmd_flat)
                return self._handle_query(validated)
            if command == "db.execute":
                from multiprocess_framework.modules.sql_module.commands import DBExecuteCommand

                validated = DBExecuteCommand.model_validate(cmd_flat)
                return self._handle_execute(validated)
            if command == "db.insert":
                from multiprocess_framework.modules.sql_module.commands import DBInsertCommand

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
        table = self._validate_identifier(cmd.table)
        data = cmd.data
        for key in data.keys():
            self._validate_identifier(key)
        cols = ", ".join(f'"{k}"' for k in data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        sql = f'INSERT INTO "{table}" ({cols}) VALUES ({placeholders})'
        rows = self.execute(sql, data)
        return {"status": "success", "rows": rows}
