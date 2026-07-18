# -*- coding: utf-8 -*-
"""Тесты тонкой конфигурации истории телеметрии прототипа.

Generic-движок выборки покрыт тестами во фреймворке
(frontend_module/tests/state/test_telemetry_history.py). Здесь проверяется
только прикладная политика: путь к БД (env-override) и фабрика источника под
схему стока telemetry_sink (таблица + whitelist колонок).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from multiprocess_framework.modules.frontend_module.state import TelemetryHistorySource
from multiprocess_prototype.frontend.state.telemetry_history import (
    ALLOWED_METRICS,
    TELEMETRY_TABLE,
    make_history_source,
    resolve_telemetry_db_path,
)


class TestResolveTelemetryDbPath:
    def test_default_path(self, monkeypatch) -> None:
        monkeypatch.delenv("INSPECTOR_TELEMETRY_DB", raising=False)
        assert resolve_telemetry_db_path() == "data/telemetry.db"

    def test_env_override(self, monkeypatch, tmp_path: Path) -> None:
        custom = str(tmp_path / "custom_telemetry.db")
        monkeypatch.setenv("INSPECTOR_TELEMETRY_DB", custom)
        assert resolve_telemetry_db_path() == custom


class TestMakeHistorySource:
    def test_schema_constants_match_telemetry_sink(self) -> None:
        assert ALLOWED_METRICS == frozenset({"fps", "latency_ms", "uptime_s", "status"})
        assert TELEMETRY_TABLE == "telemetry_snapshots"

    def test_factory_builds_source_with_prototype_schema(self, monkeypatch) -> None:
        monkeypatch.delenv("INSPECTOR_TELEMETRY_DB", raising=False)
        source = make_history_source()
        assert isinstance(source, TelemetryHistorySource)
        assert source.db_path == "data/telemetry.db"
        assert source.allowed_metrics == ALLOWED_METRICS

    def test_factory_explicit_db_path(self, tmp_path: Path) -> None:
        custom = str(tmp_path / "t.db")
        source = make_history_source(custom)
        assert source.db_path == custom

    def test_factory_source_reads_prototype_table(self, tmp_path: Path) -> None:
        """Сквозная проверка: фабрика собирает источник, читающий telemetry_snapshots."""
        db_path = tmp_path / "telemetry.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            f"CREATE TABLE {TELEMETRY_TABLE} "
            "(id INTEGER PRIMARY KEY, ts REAL, process_name TEXT, fps REAL, latency_ms REAL)"
        )
        conn.execute(f"INSERT INTO {TELEMETRY_TABLE} (ts, process_name, fps) VALUES (1.0, 'camera_0', 30.0)")
        conn.commit()
        conn.close()

        source = make_history_source(str(db_path))
        assert source.list_range("camera_0", 0.0, 10.0, ("fps",)) == [{"ts": 1.0, "fps": 30.0}]
