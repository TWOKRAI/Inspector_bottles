"""DatabasePlugin — хранение результатов детекции в БД.

Output-плагин: принимает detection_result → буферизует → batch insert.

Использует configure_managers() для создания SQLManager до основного lifecycle,
т.к. SQLManager должен существовать до configure() других плагинов.
"""

from __future__ import annotations

import importlib

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.sql_module import SQLManager, SQLManagerConfig
from multiprocess_framework.modules.sql_module.adapters.schema_mapper import SchemaBaseMapper
from multiprocess_prototype.backend.processes.database.adapter import DatabaseAdapter
from multiprocess_prototype.backend.processes.database.commands import build_command_table
from multiprocess_prototype.services.database.service import DatabaseService


@register_plugin("database", category="output", description="Хранение результатов в SQLite/PostgreSQL")
class DatabasePlugin(ProcessModulePlugin):
    """Хранение результатов детекции в БД."""

    name = "database"
    category = "output"
    inputs = []
    outputs = []
    commands = {}  # регистрация вручную

    def configure_managers(self, ctx: PluginContext) -> None:
        """Ранняя инициализация: создать SQLManager до основного lifecycle."""
        cfg = ctx.config
        db_url = cfg.get("db_url", "sqlite:///./data/db/inspector.db")

        # Создание директории для SQLite
        if db_url.startswith("sqlite:///"):
            from pathlib import Path
            db_path = db_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        sql_config = SQLManagerConfig(
            url=db_url,
            dialect=cfg.get("db_dialect", "sqlite"),
            mode="sync",
            fork_safe=True,
        )

        managers = {}
        process = ctx._process
        if process.logger_manager:
            managers["logger"] = process.logger_manager
        if getattr(process, "error_manager", None):
            managers["errors"] = process.error_manager

        self._sql_manager = SQLManager(config=sql_config, managers=managers, process=process)
        self._sql_manager.initialize()
        process.register_manager("sql", self._sql_manager, enabled=True)

        ctx.log_info(f"DatabasePlugin: SQLManager создан ({db_url})")

    def configure(self, ctx: PluginContext) -> None:
        """IDLE → READY: схема, таблица, сервис, команды, StateProxy."""
        cfg = ctx.config
        self._ctx = ctx

        # Загрузка схемы и создание таблицы
        schema_path = cfg.get(
            "schema_module_path", "multiprocess_prototype.services.database.schema"
        )
        schema_name = cfg.get("schema_class_name", "DetectionSchema")
        schema_module = importlib.import_module(schema_path)
        self._detection_schema = getattr(schema_module, schema_name)
        mapper = SchemaBaseMapper()
        create_sql = DatabaseService.build_create_table_sql(self._detection_schema, mapper)
        self._sql_manager.execute(create_sql)

        # Адаптер и сервис
        adapter = DatabaseAdapter(ctx._process)
        self._service = DatabaseService(
            output=adapter,
            batch_size=cfg.get("batch_size", 50),
            flush_interval_sec=cfg.get("flush_interval_sec", 1.0),
        )

        # Команды
        cmd_table = build_command_table(self._service, self._sql_manager)
        for cmd, handler in cmd_table.items():
            ctx.command_manager.register_command(cmd, handler)

        # StateProxy
        from multiprocess_framework.modules.state_store_module import StateProxy

        self._state_proxy = StateProxy(
            "database",
            router=ctx.router_manager,
            server_target="ProcessManager",
        )
        ctx.router_manager.register_message_handler(
            "state.changed", self._state_proxy.on_state_changed
        )

        ctx.log_info("DatabasePlugin configured")

    def start(self, ctx: PluginContext) -> None:
        """READY → RUNNING: начальный state."""
        self._state_proxy.set("database.state.status", "initialized")
        ctx.log_info("DatabasePlugin ready")

    def shutdown(self, ctx: PluginContext) -> None:
        """* → STOPPED: flush буфера → StateProxy → SQLManager."""
        # Flush буфера
        if hasattr(self, "_service") and self._service:
            try:
                result = self._service.flush()
                if result.get("rows", 0) > 0:
                    ctx.log_info(f"DatabasePlugin shutdown flush: {result['rows']} rows")
            except Exception as e:
                ctx.log_error(f"DatabasePlugin flush error: {e}")

        # StateProxy
        if hasattr(self, "_state_proxy"):
            self._state_proxy.set("database.state.status", "shutdown")
            self._state_proxy.shutdown()

        # SQLManager
        if hasattr(self, "_sql_manager") and self._sql_manager:
            try:
                self._sql_manager.shutdown()
            except Exception as e:
                ctx.log_error(f"SQLManager shutdown error: {e}")

        ctx.log_info("DatabasePlugin shutdown complete")
