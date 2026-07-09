# -*- coding: utf-8 -*-
"""Тесты StoreTapChannel (Ф5.20a): LogRecord-dict → ObservabilityStore."""

from __future__ import annotations

from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityStore,
    StoreTapChannel,
)


def _log_record_dict(level="ERROR", message="boom", module="worker_module", **extra):
    # Форма LogRecord.to_dict()
    return {
        "timestamp": 12.5,
        "level": level,
        "scope": "system",
        "message": message,
        "module": module,
        "extra": dict(extra),
    }


class TestStoreTapChannel:
    def test_write_normalizes_to_error_row(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store)  # kind='error' по умолчанию

        tap.write(_log_record_dict(level="ERROR", message="boom", error_type="ValueError"))

        rows = store.list_records(kind="error")
        assert len(rows) == 1
        r = rows[0]
        assert r["kind"] == "error"
        assert r["severity"] == "error"  # 'ERROR' → lower
        assert r["message"] == "boom"
        assert r["module"] == "worker_module"
        assert r["ts"] == 12.5
        assert r["extra"]["context"] == {"error_type": "ValueError"}
        store.close()

    def test_write_critical_lowercased(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        StoreTapChannel(store).write(_log_record_dict(level="CRITICAL", message="dead"))
        assert store.list_records(kind="error")[0]["severity"] == "critical"
        store.close()

    def test_write_failure_does_not_raise(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.close()  # закрыли → append бросит внутри, tap глушит
        result = StoreTapChannel(store).write(_log_record_dict())
        assert result["status"] == "error"

    def test_name_and_close(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store, name="my_tap")
        assert tap.name == "my_tap"
        tap.close()  # no-op, не бросает
        store.close()
