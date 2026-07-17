# -*- coding: utf-8 -*-
"""telemetry_history.py — тонкая конфигурация read-стороны истории телеметрии.

Generic-движок выборки живёт во фреймворке
(:class:`multiprocess_framework.modules.frontend_module.state.TelemetryHistorySource`).
Здесь — ТОЛЬКО прикладная политика прототипа: схема стока телеметрии
(плагин ``telemetry_sink``: таблица ``telemetry_snapshots``, whitelist колонок)
и путь к файлу БД.

Путь к БД изолирован в ОДНОМ месте (``resolve_telemetry_db_path``): переезд
кода стока эту функцию не затронет, менять придётся только её тело.
"""

from __future__ import annotations

import os

from multiprocess_framework.modules.frontend_module.state import TelemetryHistorySource

# Whitelist колонок-метрик ``telemetry_snapshots``
# (Plugins/io/telemetry_sink/schemas.py::TelemetrySnapshot). Защита от
# SQL-инъекции через имя колонки: в SELECT подставляются ТОЛЬКО эти имена,
# всё остальное из ``metrics`` молча отбрасывается.
ALLOWED_METRICS: frozenset[str] = frozenset({"fps", "latency_ms", "uptime_s", "status"})

# Имя таблицы истории (см. TelemetrySnapshot.SQLMeta.table_name).
TELEMETRY_TABLE = "telemetry_snapshots"


def resolve_telemetry_db_path() -> str:
    """Путь к SQLite-файлу истории телеметрии — единая точка в GUI-слое.

    Приоритет: env ``INSPECTOR_TELEMETRY_DB`` → дефолт ``data/telemetry.db``
    (тот же дефолт, что у ``TelemetrySinkRegisters.db_path`` — относительно cwd
    процесса; GUI и telemetry_sink запускаются из одного корня прототипа).
    """
    override = os.environ.get("INSPECTOR_TELEMETRY_DB")
    return override if override else "data/telemetry.db"


def make_history_source(db_path: str | None = None) -> TelemetryHistorySource:
    """Собрать generic-источник истории под схему стока телеметрии прототипа.

    Args:
        db_path: путь к SQLite-файлу. None → ``resolve_telemetry_db_path()``.
    """
    return TelemetryHistorySource(
        db_path if db_path is not None else resolve_telemetry_db_path(),
        table_name=TELEMETRY_TABLE,
        allowed_metrics=ALLOWED_METRICS,
    )


__all__ = [
    "TelemetryHistorySource",
    "make_history_source",
    "resolve_telemetry_db_path",
    "ALLOWED_METRICS",
    "TELEMETRY_TABLE",
]
