# -*- coding: utf-8 -*-
"""Тесты read-стороны telemetry.db (Task 2.1, план gui-telemetry-read-model).

Проверяет: диапазонная выборка с даунсемплом до max_points; отказоустойчивость
(нет файла / нет таблицы → пустой список, не исключение); whitelist метрик
(неизвестное имя колонки игнорируется, не подставляется в SQL).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from multiprocess_prototype.frontend.state.telemetry_history import (
    ALLOWED_METRICS,
    TelemetryHistorySource,
    resolve_telemetry_db_path,
)


def _make_db(path: Path, rows: list[tuple[float, str, float, float]]) -> None:
    """Собрать тестовую SQLite-БД со схемой telemetry_snapshots.

    rows: (ts, process_name, fps, latency_ms).
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE telemetry_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            process_name TEXT NOT NULL,
            fps REAL,
            latency_ms REAL,
            uptime_s REAL,
            status TEXT,
            extra TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO telemetry_snapshots (ts, process_name, fps, latency_ms) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()


# ------------------------------------------------------------------ #
#  Диапазонная выборка + даунсемпл                                     #
# ------------------------------------------------------------------ #


class TestListRangeDownsample:
    def test_downsamples_to_at_most_max_points(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        rows = [(float(i), "camera_0", float(i), float(i) * 2.0) for i in range(500)]
        _make_db(db_path, rows)

        source = TelemetryHistorySource(str(db_path))
        result = source.list_range("camera_0", 0.0, 499.0, ("fps", "latency_ms"), max_points=100)

        assert 0 < len(result) <= 100
        # Хронологический порядок сохранён.
        assert result == sorted(result, key=lambda r: r["ts"])
        # Последняя точка диапазона гарантированно попадает в прореженную выборку.
        assert result[-1]["ts"] == 499.0

    def test_no_downsample_when_under_max_points(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        rows = [(float(i), "camera_0", float(i), float(i)) for i in range(10)]
        _make_db(db_path, rows)

        source = TelemetryHistorySource(str(db_path))
        result = source.list_range("camera_0", 0.0, 9.0, ("fps",), max_points=100)

        assert len(result) == 10

    def test_filters_by_process_name_and_ts_bounds(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        rows = [
            (1.0, "camera_0", 10.0, 5.0),
            (2.0, "camera_0", 20.0, 6.0),
            (100.0, "camera_0", 30.0, 7.0),  # вне диапазона выборки
            (1.5, "other_proc", 99.0, 1.0),  # чужой процесс
        ]
        _make_db(db_path, rows)

        source = TelemetryHistorySource(str(db_path))
        result = source.list_range("camera_0", 0.0, 10.0, ("fps",), max_points=100)

        assert len(result) == 2
        assert {r["fps"] for r in result} == {10.0, 20.0}

    def test_record_shape_is_dict_with_ts_and_requested_metrics(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(1.0, "camera_0", 10.0, 5.0)])

        source = TelemetryHistorySource(str(db_path))
        result = source.list_range("camera_0", 0.0, 10.0, ("fps", "latency_ms"), max_points=10)

        assert result == [{"ts": 1.0, "fps": 10.0, "latency_ms": 5.0}]


# ------------------------------------------------------------------ #
#  Отказоустойчивость: нет файла / нет таблицы → пусто, не исключение #
# ------------------------------------------------------------------ #


class TestMissingDbIsFaultTolerant:
    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        source = TelemetryHistorySource(str(tmp_path / "no_such_file.db"))
        result = source.list_range("camera_0", 0.0, 100.0, ("fps",), max_points=10)
        assert result == []

    def test_missing_table_returns_empty_list(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()

        source = TelemetryHistorySource(str(db_path))
        result = source.list_range("camera_0", 0.0, 100.0, ("fps",), max_points=10)
        assert result == []

    def test_empty_range_returns_empty_list(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(1.0, "camera_0", 10.0, 5.0)])

        source = TelemetryHistorySource(str(db_path))
        result = source.list_range("camera_0", 1000.0, 2000.0, ("fps",), max_points=10)
        assert result == []


# ------------------------------------------------------------------ #
#  Whitelist метрик                                                    #
# ------------------------------------------------------------------ #


class TestMetricsWhitelist:
    def test_unknown_metric_is_ignored_known_still_returned(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(1.0, "camera_0", 10.0, 5.0)])

        source = TelemetryHistorySource(str(db_path))
        # "; DROP TABLE ..." — попытка инъекции через имя метрики: whitelist
        # отбрасывает её до подстановки в SQL, известная метрика возвращается.
        result = source.list_range(
            "camera_0",
            0.0,
            10.0,
            ("fps", "; DROP TABLE telemetry_snapshots;--"),
            max_points=10,
        )
        assert result == [{"ts": 1.0, "fps": 10.0}]
        # Таблица пережила запрос — инъекция не сработала.
        conn = sqlite3.connect(str(db_path))
        assert conn.execute("SELECT COUNT(*) FROM telemetry_snapshots").fetchone()[0] == 1
        conn.close()

    def test_all_metrics_unknown_returns_empty_without_query(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(1.0, "camera_0", 10.0, 5.0)])

        source = TelemetryHistorySource(str(db_path))
        result = source.list_range("camera_0", 0.0, 10.0, ("bogus_metric",), max_points=10)
        assert result == []

    def test_allowed_metrics_matches_telemetry_snapshot_columns(self) -> None:
        assert ALLOWED_METRICS == frozenset({"fps", "latency_ms", "uptime_s", "status"})


# ------------------------------------------------------------------ #
#  resolve_telemetry_db_path — единая точка пути к БД                 #
# ------------------------------------------------------------------ #


class TestResolveTelemetryDbPath:
    def test_default_path(self, monkeypatch) -> None:
        monkeypatch.delenv("INSPECTOR_TELEMETRY_DB", raising=False)
        assert resolve_telemetry_db_path() == "data/telemetry.db"

    def test_env_override(self, monkeypatch, tmp_path: Path) -> None:
        custom = str(tmp_path / "custom_telemetry.db")
        monkeypatch.setenv("INSPECTOR_TELEMETRY_DB", custom)
        assert resolve_telemetry_db_path() == custom
