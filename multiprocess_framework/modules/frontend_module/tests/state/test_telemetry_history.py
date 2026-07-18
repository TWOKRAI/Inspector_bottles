# -*- coding: utf-8 -*-
"""Тесты generic TelemetryHistorySource — read-сторона SQLite-стока телеметрии.

Проверяет: диапазонная выборка с даунсемплом до max_points; отказоустойчивость
(нет файла / нет таблицы → пустой список, не исключение); whitelist метрик
(неизвестное имя колонки игнорируется, не подставляется в SQL); generic-параметры
(имя таблицы/ключевой колонки — конструктор, не хардкод).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from multiprocess_framework.modules.frontend_module.state.telemetry_history import (
    TelemetryHistorySource,
)

# Прикладная схема для тестов (эквивалент стока telemetry_sink).
_TABLE = "telemetry_snapshots"
_METRICS = frozenset({"fps", "latency_ms", "uptime_s", "status"})


def _source(db_path: Path) -> TelemetryHistorySource:
    return TelemetryHistorySource(str(db_path), table_name=_TABLE, allowed_metrics=_METRICS)


def _make_db(path: Path, rows: list[tuple[float, str, float, float]]) -> None:
    """Собрать тестовую SQLite-БД со схемой telemetry_snapshots.

    rows: (ts, process_name, fps, latency_ms).
    """
    conn = sqlite3.connect(str(path))
    conn.execute(
        f"""
        CREATE TABLE {_TABLE} (
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
        f"INSERT INTO {_TABLE} (ts, process_name, fps, latency_ms) VALUES (?, ?, ?, ?)",
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

        result = _source(db_path).list_range("camera_0", 0.0, 499.0, ("fps", "latency_ms"), max_points=100)

        assert 0 < len(result) <= 100
        assert result == sorted(result, key=lambda r: r["ts"])
        # Последняя точка диапазона гарантированно попадает в прореженную выборку.
        assert result[-1]["ts"] == 499.0

    def test_no_downsample_when_under_max_points(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(float(i), "camera_0", float(i), float(i)) for i in range(10)])

        result = _source(db_path).list_range("camera_0", 0.0, 9.0, ("fps",), max_points=100)
        assert len(result) == 10

    def test_filters_by_key_and_ts_bounds(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        rows = [
            (1.0, "camera_0", 10.0, 5.0),
            (2.0, "camera_0", 20.0, 6.0),
            (100.0, "camera_0", 30.0, 7.0),  # вне диапазона выборки
            (1.5, "other_proc", 99.0, 1.0),  # чужой ключ
        ]
        _make_db(db_path, rows)

        result = _source(db_path).list_range("camera_0", 0.0, 10.0, ("fps",), max_points=100)
        assert len(result) == 2
        assert {r["fps"] for r in result} == {10.0, 20.0}

    def test_record_shape_is_dict_with_ts_and_requested_metrics(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(1.0, "camera_0", 10.0, 5.0)])

        result = _source(db_path).list_range("camera_0", 0.0, 10.0, ("fps", "latency_ms"), max_points=10)
        assert result == [{"ts": 1.0, "fps": 10.0, "latency_ms": 5.0}]


# ------------------------------------------------------------------ #
#  Отказоустойчивость: нет файла / нет таблицы → пусто, не исключение #
# ------------------------------------------------------------------ #


class TestMissingDbIsFaultTolerant:
    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        source = _source(tmp_path / "no_such_file.db")
        assert source.list_range("camera_0", 0.0, 100.0, ("fps",), max_points=10) == []

    def test_missing_table_returns_empty_list(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
        conn.close()

        assert _source(db_path).list_range("camera_0", 0.0, 100.0, ("fps",), max_points=10) == []

    def test_empty_range_returns_empty_list(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(1.0, "camera_0", 10.0, 5.0)])
        assert _source(db_path).list_range("camera_0", 1000.0, 2000.0, ("fps",), max_points=10) == []


# ------------------------------------------------------------------ #
#  Whitelist метрик                                                    #
# ------------------------------------------------------------------ #


class TestMetricsWhitelist:
    def test_unknown_metric_is_ignored_known_still_returned(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(1.0, "camera_0", 10.0, 5.0)])

        # "; DROP TABLE ..." — попытка инъекции через имя метрики: whitelist
        # отбрасывает её до подстановки в SQL, известная метрика возвращается.
        result = _source(db_path).list_range(
            "camera_0",
            0.0,
            10.0,
            ("fps", "; DROP TABLE telemetry_snapshots;--"),
            max_points=10,
        )
        assert result == [{"ts": 1.0, "fps": 10.0}]
        conn = sqlite3.connect(str(db_path))
        assert conn.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()[0] == 1
        conn.close()

    def test_all_metrics_unknown_returns_empty_without_query(self, tmp_path: Path) -> None:
        db_path = tmp_path / "telemetry.db"
        _make_db(db_path, [(1.0, "camera_0", 10.0, 5.0)])
        assert _source(db_path).list_range("camera_0", 0.0, 10.0, ("bogus_metric",), max_points=10) == []


# ------------------------------------------------------------------ #
#  Generic: имя таблицы/ключевой колонки — параметры конструктора     #
# ------------------------------------------------------------------ #


class TestGenericSchema:
    def test_custom_table_and_key_column(self, tmp_path: Path) -> None:
        db_path = tmp_path / "custom.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE metrics_log (t REAL, node TEXT, rate REAL)")
        conn.executemany(
            "INSERT INTO metrics_log (t, node, rate) VALUES (?, ?, ?)",
            [(1.0, "n1", 5.0), (2.0, "n1", 6.0), (1.0, "n2", 99.0)],
        )
        conn.commit()
        conn.close()

        source = TelemetryHistorySource(
            str(db_path),
            table_name="metrics_log",
            allowed_metrics=frozenset({"rate"}),
            ts_column="t",
            key_column="node",
        )
        result = source.list_range("n1", 0.0, 10.0, ("rate",), max_points=10)
        assert result == [{"ts": 1.0, "rate": 5.0}, {"ts": 2.0, "rate": 6.0}]
