"""DatabaseProcess — инфраструктурный контейнер для DatabaseService."""
from __future__ import annotations

import importlib
from typing import Any, Optional

from multiprocess_framework.modules.process_module import ProcessIO, ProcessModule
from multiprocess_framework.modules.sql_module import SQLManager, SQLManagerConfig
from multiprocess_framework.modules.sql_module.adapters.schema_mapper import SchemaBaseMapper
from multiprocess_prototype_v3.services.database.service import DatabaseService


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
        adapter = _DatabaseAdapter(self)
        self._service = DatabaseService(output=adapter)

        self._register_commands()
        self._log_info("DatabaseProcess ready")

    def _register_commands(self) -> None:
        """Регистрация IPC-команд.

        db.query / db.execute / db.insert — прямая делегация в SQLManager.
        db.save_detections — адаптер (распаковка args/data → сервис).
        """
        assert self.sql_manager is not None, "sql_manager must be initialized"
        sql_cmd = self.sql_manager.execute_command
        
        for cmd in ("db.query", "db.execute", "db.insert"):
            self.command_manager.register_command(cmd, sql_cmd)
        self.command_manager.register_command("db.save_detections", self._cmd_save_detections)

    def _cmd_save_detections(self, msg: dict) -> dict:
        """Адаптер: распаковать детекции из args/data и передать в сервис."""
        args = msg.get("args", {}) or msg.get("data", {})
        return self._service.save_detections(args.get("detections", []))

    def shutdown(self) -> bool:
        if self.sql_manager:
            try:
                self.sql_manager.shutdown()
            except Exception as e:
                self._log_error(f"SQLManager shutdown error: {e}")
        return super().shutdown()


class _DatabaseAdapter:
    """Реализует DatabaseOutputPort: SQL + логи через ProcessIO."""

    def __init__(self, process: DatabaseProcess) -> None:
        self._p = process  # нужен для прямого доступа к sql_manager
        self._io = ProcessIO(process)

    def execute_sql(self, sql: str, params: Optional[dict[str, Any]] = None) -> None:
        """Выполнить SQL через SQLManager (специфика БД, не IPC)."""
        self._p.sql_manager.execute(sql, params or {})

    def log_info(self, text: str) -> None:
        self._io.log_info(text)

    def log_error(self, text: str) -> None:
        self._io.log_error(text)
