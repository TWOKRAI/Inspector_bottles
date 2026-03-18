# multiprocess_prototype\processes\database_process.py
"""
DatabaseProcess — процесс с SQLManager.

Регистрирует команды db.query, db.execute, db.insert, db.save_detections.
Создаёт таблицу из схемы (DetectionSchema) при инициализации.
"""
import importlib

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.sql_module import (
    SQLManager,
    SQLManagerConfig,
    TableExporter,
    ExportFormat,
)
from multiprocess_framework.refactored.modules.sql_module.adapters.schema_mapper import SchemaBaseMapper

from multiprocess_prototype.database.utils import (
    build_create_table_sql,
    create_detection_exporter,
)


class DatabaseProcess(ProcessModule):
    """Процесс с SQLManager. Доступ к БД через команды db.query, db.execute, db.insert, db.save_detections."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_manager = None
        self._detection_schema = None

    def _init_custom_managers(self):
        """Создать SQLManager, создать таблицу из схемы, зарегистрировать команды."""
        app_cfg = self.get_config("config") or {}
        db_url = app_cfg.get("db_url", "sqlite:///./inspector.db")
        db_dialect = app_cfg.get("db_dialect", "sqlite")
        schema_module_path = app_cfg.get("schema_module_path", "multiprocess_prototype.database.schema_1")
        schema_class_name = app_cfg.get("schema_class_name", "DetectionSchema")

        sql_config = SQLManagerConfig(
            url=db_url,
            dialect=db_dialect,
            mode="sync",
            fork_safe=True,
        )
        managers = {}
        if self.logger_manager:
            managers["logger"] = self.logger_manager
        if getattr(self, "error_manager", None):
            managers["errors"] = self.error_manager
        if getattr(self, "stats_manager", None):
            managers["stats"] = self.stats_manager

        self.sql_manager = SQLManager(
            config=sql_config,
            managers=managers,
            process=self,
        )
        self.sql_manager.initialize()
        self.register_manager("sql", self.sql_manager, enabled=True)

        # Загрузка схемы и создание таблицы
        schema_module = importlib.import_module(schema_module_path)
        self._detection_schema = getattr(schema_module, schema_class_name)
        mapper = SchemaBaseMapper()
        create_sql = build_create_table_sql(self._detection_schema, mapper)
        self.sql_manager.execute(create_sql)
        self._log_info("DatabaseProcess: table detections created from schema")

        self.command_manager.register_command(
            "db.query",
            lambda msg: self.sql_manager.execute_command(msg),
        )
        self.command_manager.register_command(
            "db.execute",
            lambda msg: self.sql_manager.execute_command(msg),
        )
        self.command_manager.register_command(
            "db.insert",
            lambda msg: self.sql_manager.execute_command(msg),
        )
        self.command_manager.register_command(
            "db.save_detections",
            self._cmd_save_detections,
        )
        self.command_manager.register_command(
            "db.export_detections",
            self._cmd_export_detections,
        )

        self._log_info(
            "DatabaseProcess: SQLManager ready, commands db.query/execute/insert/save_detections registered"
        )

    def _cmd_save_detections(self, msg: dict) -> dict:
        """Сохранить детекции в БД. Payload по DetectionSchema."""
        try:
            args = msg.get("args", {}) or msg.get("data", {})
            detections = args.get("detections", [])
            if not detections:
                return {"status": "ok", "rows": 0}

            schema_class = self._detection_schema
            total = 0
            for d in detections:
                entity = schema_class.model_validate(d)
                row = entity.model_dump(exclude_none=True, exclude={"id"})
                cols = ", ".join(f'"{k}"' for k in row.keys())
                placeholders = ", ".join(f":{k}" for k in row.keys())
                sql = f'INSERT INTO "detections" ({cols}) VALUES ({placeholders})'
                self.sql_manager.execute(sql, row)
                total += 1

            self._log_info(f"DatabaseProcess: saved {total} detection(s)")
            return {"status": "success", "rows": total}
        except Exception as e:
            self._log_error(f"db.save_detections failed: {e}")
            return {"status": "error", "reason": str(e)}

    def _cmd_export_detections(self, msg: dict) -> dict:
        """Экспорт детекций в файл. args: path, format (txt|txt_table|csv|xlsx), offset, limit."""
        try:
            args = msg.get("args", {}) or msg.get("data", {})
            path = args.get("path")
            if not path:
                return {"status": "error", "reason": "path required"}
            fmt_str = args.get("format", "txt")
            offset = int(args.get("offset", 0))
            limit = args.get("limit")
            if limit is not None:
                limit = int(limit)

            fmt_map = {
                "txt": ExportFormat.TXT_READABLE,
                "txt_table": ExportFormat.TXT_TABLE,
                "csv": ExportFormat.CSV,
                "xlsx": ExportFormat.XLSX,
            }
            fmt = fmt_map.get(fmt_str, ExportFormat.TXT_READABLE)

            rows = self.sql_manager.query_range(
                table="detections",
                order_by="id",
                offset=offset,
                limit=limit,
            )
            exporter = create_detection_exporter()
            count = exporter.save(
                rows,
                path,
                format=fmt,
                title="Детекции из inspector.db",
                sheet_name="Detections",
            )
            self._log_info(f"DatabaseProcess: exported {count} detection(s) to {path}")
            return {"status": "success", "rows": count, "path": str(path)}
        except Exception as e:
            self._log_error(f"db.export_detections failed: {e}")
            return {"status": "error", "reason": str(e)}

    def shutdown(self) -> bool:
        """Завершение с освобождением SQLManager."""
        if self.sql_manager:
            try:
                self.sql_manager.shutdown()
            except Exception as e:
                self._log_error(f"SQLManager shutdown error: {e}")
        return super().shutdown()
