# -*- coding: utf-8 -*-
"""Тесты ObservabilityStore (Ф5.20a): persistence, пагинация, фильтры."""

from __future__ import annotations

import os
import sqlite3  # noqa: F401 — используется в TestProcessColumn (legacy-миграция)

from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityStore,
    resolve_default_db_path,
)


def _log_rec(module="worker_module", ts=1.0, severity="info", message="hi", process=None, **ctx):
    rec = {"kind": "log", "module": module, "ts": ts, "severity": severity, "message": message, "context": ctx}
    if process is not None:
        rec["process"] = process
    return rec


def _err_rec(module="worker_module", ts=2.0, severity="error", message="boom"):
    return {
        "kind": "error",
        "module": module,
        "ts": ts,
        "severity": severity,
        "error_type": "ValueError",
        "message": message,
        "traceback": "tb...",
        "context": {},
    }


def _stat_rec(module="worker_module", ts=3.0, metric="fps", value=30, metric_type="gauge"):
    return {
        "kind": "stats",
        "module": module,
        "ts": ts,
        "metric": metric,
        "value": value,
        "metric_type": metric_type,
        "tags": {},
    }


class TestPersistence:
    def test_append_then_read(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        assert store.append_records([_log_rec(message="a"), _log_rec(message="b")]) == 2
        rows = store.list_records(kind="log")
        assert [r["message"] for r in rows] == ["b", "a"]  # newest first
        store.close()

    def test_survives_reopen(self, tmp_path):
        """Стор переживает пересоздание процесса (акцептанс 5.20)."""
        db = str(tmp_path / "obs.db")
        s1 = ObservabilityStore(db)
        s1.append_records([_err_rec(message="crash")])
        s1.close()

        s2 = ObservabilityStore(db)  # «новый процесс» открыл тот же файл
        rows = s2.list_records(kind="error")
        assert len(rows) == 1
        assert rows[0]["message"] == "crash"
        assert rows[0]["extra"]["error_type"] == "ValueError"
        s2.close()

    def test_append_empty_is_noop(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        assert store.append_records([]) == 0
        assert store.count() == 0
        store.close()


class TestNormalization:
    def test_stats_row_uses_metric_type_and_value(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_stat_rec(metric="fps", value=25, metric_type="gauge")])
        row = store.list_records(kind="stats")[0]
        assert row["message"] == "fps"
        assert row["severity"] == "gauge"  # для stats severity = metric_type
        assert row["extra"]["value"] == 25
        store.close()

    def test_log_context_in_extra(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_log_rec(message="m", worker="w1")])
        row = store.list_records(kind="log")[0]
        assert row["extra"]["context"] == {"worker": "w1"}
        store.close()


class TestProcessColumn:
    """5.21 (c): колонка process — имя процесса-источника, с миграцией старой БД."""

    def test_explicit_process_stored_and_read(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_log_rec(module="worker_module", process="camera_0", message="m")])
        row = store.list_records(kind="log")[0]
        assert row["process"] == "camera_0"  # процесс-источник
        assert row["module"] == "worker_module"  # scope сохранён отдельно
        store.close()

    def test_missing_process_falls_back_to_module(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_log_rec(module="main", message="m")])  # без process
        row = store.list_records(kind="log")[0]
        assert row["process"] == "main"
        store.close()

    def test_migration_adds_process_column_to_legacy_db(self, tmp_path):
        """Файл без колонки process (дореформенная схема) → ALTER доливает её."""
        db = str(tmp_path / "legacy.db")
        legacy = sqlite3.connect(db)
        legacy.execute(
            "CREATE TABLE records (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, "
            "module TEXT NOT NULL, ts REAL NOT NULL, severity TEXT, message TEXT, extra TEXT)"
        )
        legacy.execute(
            "INSERT INTO records (kind, module, ts, severity, message, extra) "
            "VALUES ('log','old_mod',1.0,'info','legacy','{}')"
        )
        legacy.commit()
        legacy.close()

        store = ObservabilityStore(db)  # открытие мигрирует схему
        store.append_records([_log_rec(module="worker_module", process="camera_0", message="new")])
        rows = store.list_records(kind="log")
        by_msg = {r["message"]: r for r in rows}
        assert by_msg["legacy"]["process"] == "old_mod"  # NULL → падаем на module
        assert by_msg["new"]["process"] == "camera_0"
        store.close()


class TestQuery:
    def _seed(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records(
            [
                _log_rec(ts=1, severity="info", message="l1"),
                _log_rec(ts=2, severity="warning", message="l2"),
                _err_rec(ts=3, severity="error", message="e1"),
                _stat_rec(ts=4, metric="fps"),
            ]
        )
        return store

    def test_filter_by_kind(self, tmp_path):
        store = self._seed(tmp_path)
        assert store.count(kind="log") == 2
        assert store.count(kind="error") == 1
        assert store.count() == 4
        store.close()

    def test_filter_by_severity(self, tmp_path):
        store = self._seed(tmp_path)
        rows = store.list_records(kind="log", severity_in=["WARNING"])  # case-insensitive
        assert [r["message"] for r in rows] == ["l2"]
        store.close()

    def test_filter_by_module(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_log_rec(module="a", message="x"), _log_rec(module="b", message="y")])
        rows = store.list_records(module="b")
        assert [r["message"] for r in rows] == ["y"]
        store.close()

    def test_pagination(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_log_rec(message=f"m{i}") for i in range(10)])
        page1 = store.list_records(kind="log", offset=0, limit=3)
        page2 = store.list_records(kind="log", offset=3, limit=3)
        assert [r["message"] for r in page1] == ["m9", "m8", "m7"]
        assert [r["message"] for r in page2] == ["m6", "m5", "m4"]
        store.close()

    def test_oldest_first_order(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.append_records([_log_rec(message="a"), _log_rec(message="b")])
        rows = store.list_records(kind="log", newest_first=False)
        assert [r["message"] for r in rows] == ["a", "b"]
        store.close()

    def test_clear_by_kind(self, tmp_path):
        store = self._seed(tmp_path)
        assert store.clear(kind="log") == 2
        assert store.count(kind="log") == 0
        assert store.count(kind="error") == 1
        store.close()


class TestDefaultPath:
    def test_resolve_uses_env(self, monkeypatch):
        monkeypatch.setenv("INSPECTOR_LOG_DIR", "/tmp/mylogs")
        assert resolve_default_db_path() == os.path.join("/tmp/mylogs", "observability.db")

    def test_resolve_fallback(self, monkeypatch):
        monkeypatch.delenv("INSPECTOR_LOG_DIR", raising=False)
        monkeypatch.delenv("MULTIPROCESS_LOG_DIR", raising=False)
        assert resolve_default_db_path() == os.path.join("logs", "observability.db")
