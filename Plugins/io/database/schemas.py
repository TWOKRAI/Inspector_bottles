"""Схемы таблиц database-плагина.

DetectionSchema — одна строка = один результат обработки кадра (detection-событие).
Повторяет колонки исторической таблицы `detections` (raw sqlite3 → SQLManager auto-DDL).

Маппинг старого CREATE TABLE → SchemaBase:
  id INTEGER PRIMARY KEY AUTOINCREMENT  → id: Optional[int] = None
  timestamp REAL NOT NULL               → timestamp: float
  frame_id INTEGER                      → frame_id: Optional[int] = None
  camera_id INTEGER                     → camera_id: Optional[int] = None
  event_type TEXT                       → event_type: Optional[str] = None
  data TEXT                             → data: Optional[str] = None
  created_at REAL DEFAULT unixepoch     → created_at: float (проставляется в коде, см. ниже)

`created_at` — SQL-default-выражение `unixepoch('now')` НЕ переносится в DDLBuilder
(он строит статичные DEFAULT, не SQL-функции), поэтому значение проставляется в коде
при flush (`DatabasePlugin._do_flush`: created_at=time.time()).
"""

from __future__ import annotations

from typing import Optional

from multiprocess_framework.modules.data_schema_module import SchemaBase


class DetectionSchema(SchemaBase):
    """Запись результата обработки кадра (wide-таблица detections).

    id — autoincrement PK (Optional[int]=None → INTEGER PRIMARY KEY AUTOINCREMENT
    в DDLBuilder; insert_many передаёт id=None, SQLite присваивает сам).
    """

    class SQLMeta:
        table_name = "detections"
        indexes = [("timestamp",), ("event_type",)]

    id: Optional[int] = None
    timestamp: float
    frame_id: Optional[int] = None
    camera_id: Optional[int] = None
    event_type: Optional[str] = None
    data: Optional[str] = None
    created_at: Optional[float] = None
