"""Схемы таблиц telemetry_sink.

TelemetrySnapshot — одна строка = снимок метрик одного процесса в момент ts
(wide-таблица: фиксированные метрики — колонки, нестандартный хвост — JSON в extra).

Полный набор (Task 1.2): fps / latency_ms / uptime_s / status + extra (JSON-хвост
для нестандартных листьев: per-worker метрики, broken_wires, active и т.п.).
Строка-сводка по системе пишется с process_name='system' (fps←system.health.avg_fps).
"""

from __future__ import annotations

from typing import Optional

from multiprocess_framework.modules.data_schema_module import SchemaBase


class TelemetrySnapshot(SchemaBase):
    """Снимок телеметрии одного процесса (wide-таблица).

    id — autoincrement PK (Optional[int]=None → INTEGER PRIMARY KEY AUTOINCREMENT
    в DDLBuilder; insert_many передаёт id=None, SQLite присваивает сам).

    Стандартные метрики — отдельные колонки (`processes.<P>.state.<metric>`):
      fps / latency_ms / uptime_s (← uptime) / status.
    Нестандартные листья (per-worker `workers.*`, доп. поля system) уходят в
    `extra` как JSON-строка — схема не ломается при добавлении новых метрик.
    """

    class SQLMeta:
        table_name = "telemetry_snapshots"
        indexes = [("ts",), ("process_name", "ts")]

    id: Optional[int] = None
    ts: float
    process_name: str
    fps: Optional[float] = None
    latency_ms: Optional[float] = None
    uptime_s: Optional[float] = None
    status: Optional[str] = None
    extra: Optional[str] = None
