"""DatabaseService — бизнес-логика работы с данными детекций."""
from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from multiprocess_prototype.services.database.ports import DatabaseOutputPort

from multiprocess_prototype.services.database.schema import DetectionSchema


class DatabaseService:
    """Сервис БД. Буферизация и batch-сохранение детекций через порт."""

    def __init__(
        self,
        output: DatabaseOutputPort,
        batch_size: int = 50,
        flush_interval_sec: float = 1.0,
    ) -> None:
        self._out = output
        self._batch_size = batch_size
        self._flush_interval = flush_interval_sec
        self._pending: list[dict] = []
        self._last_flush_time: float = time.time()

    def save_detections(self, detections: list[dict]) -> dict:
        """Валидировать детекции, добавить в буфер, flush при необходимости."""
        if not detections:
            return {"status": "ok", "rows": 0}
        try:
            for d in detections:
                entity = DetectionSchema.model_validate(d)
                row = entity.model_dump(exclude_none=True, exclude={"id"})
                self._pending.append(row)
            self._maybe_flush()
            return {"status": "buffered", "pending": len(self._pending)}
        except Exception as e:
            self._out.log_error(f"db.save_detections failed: {e}")
            return {"status": "error", "reason": str(e)}

    def _maybe_flush(self) -> None:
        """Выполнить flush если буфер заполнен или истёк интервал."""
        now = time.time()
        if (
            len(self._pending) >= self._batch_size
            or (now - self._last_flush_time) >= self._flush_interval
        ):
            self.flush()

    def flush(self) -> dict:
        """Принудительно записать все буферизованные детекции в БД.

        Все rows в буфере должны иметь одинаковый набор ключей.
        При несовпадении — fallback на поштучный INSERT.
        """
        if not self._pending:
            return {"status": "ok", "rows": 0}

        rows = list(self._pending)
        self._pending.clear()
        self._last_flush_time = time.time()

        # Проверяем, что все rows имеют одинаковый набор ключей
        first_keys = set(rows[0].keys())
        uniform = all(set(r.keys()) == first_keys for r in rows)

        if uniform:
            return self._flush_batch(rows)
        else:
            return self._flush_fallback(rows)

    def _flush_batch(self, rows: list[dict]) -> dict:
        """Batch INSERT через execute_many (один набор ключей для всех rows)."""
        try:
            first = rows[0]
            cols = ", ".join(f'"{k}"' for k in first.keys())
            placeholders = ", ".join(f":{k}" for k in first.keys())
            sql = f'INSERT INTO "detections" ({cols}) VALUES ({placeholders})'
            self._out.execute_many(sql, rows)
            return {"status": "success", "rows": len(rows)}
        except Exception as e:
            self._out.log_error(f"db.flush failed: {e}")
            return {"status": "error", "reason": str(e)}

    def _flush_fallback(self, rows: list[dict]) -> dict:
        """Поштучный INSERT — fallback при несовпадении ключей в rows."""
        self._out.log_info(
            f"db.flush: неоднородные ключи в batch ({len(rows)} rows), "
            "fallback на поштучный INSERT"
        )
        total = 0
        errors = []
        for row in rows:
            try:
                cols = ", ".join(f'"{k}"' for k in row.keys())
                placeholders = ", ".join(f":{k}" for k in row.keys())
                sql = f'INSERT INTO "detections" ({cols}) VALUES ({placeholders})'
                self._out.execute_sql(sql, row)
                total += 1
            except Exception as e:
                self._out.log_error(f"db.flush fallback row failed: {e}")
                errors.append(str(e))
        if errors:
            return {"status": "partial", "rows": total, "errors": errors}
        return {"status": "success", "rows": total}

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
