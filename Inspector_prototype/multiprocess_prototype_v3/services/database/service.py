"""DatabaseService — бизнес-логика работы с данными детекций."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from multiprocess_prototype_v3.services.database.ports import DatabaseOutputPort

from multiprocess_prototype_v3.services.database.schema import DetectionSchema


class DatabaseService:
    """Сервис БД. Валидация и сохранение детекций через порт."""

    def __init__(self, output: DatabaseOutputPort) -> None:
        self._out = output

    def save_detections(self, detections: list[dict]) -> dict:
        """Валидировать и сохранить детекции в БД через порт."""
        if not detections:
            return {"status": "ok", "rows": 0}
        try:
            total = 0
            for d in detections:
                entity = DetectionSchema.model_validate(d)
                row = entity.model_dump(exclude_none=True, exclude={"id"})
                cols = ", ".join(f'"{k}"' for k in row.keys())
                placeholders = ", ".join(f":{k}" for k in row.keys())
                self._out.execute_sql(
                    f'INSERT INTO "detections" ({cols}) VALUES ({placeholders})', row
                )
                total += 1
            return {"status": "success", "rows": total}
        except Exception as e:
            self._out.log_error(f"db.save_detections failed: {e}")
            return {"status": "error", "reason": str(e)}

    @staticmethod
    def build_create_table_sql(schema_class, schema_mapper, if_not_exists: bool = True) -> str:
        """Сгенерировать SQL для создания таблицы из Pydantic-схемы."""
        meta = schema_mapper.schema_to_table_meta(schema_class)
        table_name = meta["table_name"]
        columns = meta.get("columns", {})
        primary_key = meta.get("primary_key", [])
        _type_map = {
            "Integer": "INTEGER",
            "Float": "REAL",
            "String": "TEXT",
            "Boolean": "INTEGER",
            "DateTime": "TEXT",
        }
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
