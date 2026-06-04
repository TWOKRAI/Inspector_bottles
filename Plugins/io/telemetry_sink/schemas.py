"""Схемы таблиц telemetry_sink.

TelemetrySnapshot — одна строка = снимок метрик одного процесса в момент ts.

Минимальный вариант (Task 1.1, vertical slice): id / ts / process_name / fps.
Расширение до полного набора (latency_ms, uptime_s, status, extra) — Task 1.2.
"""

from __future__ import annotations

from typing import Optional

from multiprocess_framework.modules.data_schema_module import SchemaBase


class TelemetrySnapshot(SchemaBase):
    """Снимок телеметрии одного процесса (wide-таблица).

    id — autoincrement PK (Optional[int]=None → INTEGER PRIMARY KEY AUTOINCREMENT
    в DDLBuilder; insert_many передаёт id=None, SQLite присваивает сам).
    """

    class SQLMeta:
        table_name = "telemetry_snapshots"
        indexes = [("ts",), ("process_name", "ts")]

    id: Optional[int] = None
    ts: float
    process_name: str
    fps: Optional[float] = None
