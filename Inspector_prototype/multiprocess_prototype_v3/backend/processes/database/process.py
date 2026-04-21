"""DatabaseProcess — инфраструктурный контейнер для DatabaseService.

Тонкий ProcessModule: SQLManager lifecycle, команды.
Команды — в commands.py, адаптер — в adapter.py.
"""
from __future__ import annotations

import importlib

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.sql_module import SQLManager, SQLManagerConfig
from multiprocess_framework.modules.sql_module.adapters.schema_mapper import SchemaBaseMapper
from multiprocess_prototype_v3.services.database.service import DatabaseService

from .adapter import DatabaseAdapter
from .commands import build_command_table


class DatabaseProcess(ProcessModule):
    """Процесс БД. Инфраструктура: SQLManager, команды."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_manager = None
        self._detection_schema = None
        self._service = None

    def _init_custom_managers(self) -> None:
        app_cfg = self.get_config("config") or {}
        db_url = app_cfg.get("db_url", "sqlite:///./inspector.db")

        # Создание директории для SQLite
        if db_url.startswith("sqlite:///"):
            from pathlib import Path
            db_path = db_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        sql_config = SQLManagerConfig(
            url=db_url, dialect=app_cfg.get("db_dialect", "sqlite"),
            mode="sync", fork_safe=True,
        )
        managers = {}
        if self.logger_manager:
            managers["logger"] = self.logger_manager
        if getattr(self, "error_manager", None):
            managers["errors"] = self.error_manager

        self.sql_manager = SQLManager(config=sql_config, managers=managers, process=self)
        self.sql_manager.initialize()
        self.register_manager("sql", self.sql_manager, enabled=True)

        # Загрузка схемы и создание таблицы
        schema_path = app_cfg.get(
            "schema_module_path", "multiprocess_prototype_v3.services.database.schema"
        )
        schema_name = app_cfg.get("schema_class_name", "DetectionSchema")
        schema_module = importlib.import_module(schema_path)
        self._detection_schema = getattr(schema_module, schema_name)
        mapper = SchemaBaseMapper()
        create_sql = DatabaseService.build_create_table_sql(self._detection_schema, mapper)
        self.sql_manager.execute(create_sql)

        # Адаптер и сервис
        adapter = DatabaseAdapter(self)
        self._service = DatabaseService(output=adapter)

        # Команды из таблицы
        cmd_table = build_command_table(self._service, self.sql_manager)
        for cmd, handler in cmd_table.items():
            self.command_manager.register_command(cmd, handler)

        self._log_info("DatabaseProcess ready")

    def shutdown(self) -> bool:
        if self.sql_manager:
            try:
                self.sql_manager.shutdown()
            except Exception as e:
                self._log_error(f"SQLManager shutdown error: {e}")
        return super().shutdown()
