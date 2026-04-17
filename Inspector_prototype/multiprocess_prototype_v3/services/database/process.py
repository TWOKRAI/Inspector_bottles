"""DatabaseProcess — SQLManager-based database process."""

import importlib

from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.sql_module import SQLManager, SQLManagerConfig, ExportFormat
from multiprocess_framework.modules.sql_module.adapters.schema_mapper import SchemaBaseMapper


def _build_create_table_sql(schema_class, schema_mapper, if_not_exists=True):
    meta = schema_mapper.schema_to_table_meta(schema_class)
    table_name = meta["table_name"]
    columns = meta.get("columns", {})
    primary_key = meta.get("primary_key", [])
    _type_map = {"Integer": "INTEGER", "Float": "REAL", "String": "TEXT", "Boolean": "INTEGER", "DateTime": "TEXT"}
    parts = []
    for col_name, col_info in columns.items():
        if col_name == "id" and "id" in primary_key:
            parts.append(f'  "{col_name}" INTEGER PRIMARY KEY AUTOINCREMENT')
            continue
        sa_type = col_info.get("type")
        type_name = getattr(sa_type, "__name__", "String") if sa_type else "String"
        sql_type = _type_map.get(type_name, "TEXT")
        nullable = "" if col_info.get("nullable", True) else " NOT NULL"
        parts.append(f'  "{col_name}" {sql_type}{nullable}')
    clause = " IF NOT EXISTS" if if_not_exists else ""
    return f'CREATE TABLE{clause} "{table_name}" (\n' + ",\n".join(parts) + "\n)"


class DatabaseProcess(ProcessModule):
    """Database process with SQLManager."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sql_manager = None
        self._detection_schema = None

    def _init_custom_managers(self):
        app_cfg = self.get_config("config") or {}
        db_url = app_cfg.get("db_url", "sqlite:///./inspector.db")
        sql_config = SQLManagerConfig(url=db_url, dialect=app_cfg.get("db_dialect", "sqlite"), mode="sync", fork_safe=True)
        managers = {}
        if self.logger_manager:
            managers["logger"] = self.logger_manager
        if getattr(self, "error_manager", None):
            managers["errors"] = self.error_manager

        self.sql_manager = SQLManager(config=sql_config, managers=managers, process=self)
        self.sql_manager.initialize()
        self.register_manager("sql", self.sql_manager, enabled=True)

        schema_path = app_cfg.get("schema_module_path", "multiprocess_prototype_v3.services.database.schema")
        schema_name = app_cfg.get("schema_class_name", "DetectionSchema")
        schema_module = importlib.import_module(schema_path)
        self._detection_schema = getattr(schema_module, schema_name)
        mapper = SchemaBaseMapper()
        self.sql_manager.execute(_build_create_table_sql(self._detection_schema, mapper))

        self.command_manager.register_command("db.query", lambda msg: self.sql_manager.execute_command(msg))
        self.command_manager.register_command("db.execute", lambda msg: self.sql_manager.execute_command(msg))
        self.command_manager.register_command("db.insert", lambda msg: self.sql_manager.execute_command(msg))
        self.command_manager.register_command("db.save_detections", self._cmd_save_detections)
        self._log_info("DatabaseProcess ready")

    def _cmd_save_detections(self, msg: dict) -> dict:
        try:
            args = msg.get("args", {}) or msg.get("data", {})
            detections = args.get("detections", [])
            if not detections:
                return {"status": "ok", "rows": 0}
            total = 0
            for d in detections:
                entity = self._detection_schema.model_validate(d)
                row = entity.model_dump(exclude_none=True, exclude={"id"})
                cols = ", ".join(f'"{k}"' for k in row.keys())
                placeholders = ", ".join(f":{k}" for k in row.keys())
                self.sql_manager.execute(f'INSERT INTO "detections" ({cols}) VALUES ({placeholders})', row)
                total += 1
            return {"status": "success", "rows": total}
        except Exception as e:
            self._log_error(f"db.save_detections failed: {e}")
            return {"status": "error", "reason": str(e)}

    def shutdown(self) -> bool:
        if self.sql_manager:
            try:
                self.sql_manager.shutdown()
            except Exception as e:
                self._log_error(f"SQLManager shutdown error: {e}")
        return super().shutdown()
