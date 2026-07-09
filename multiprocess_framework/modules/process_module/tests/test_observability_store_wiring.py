# -*- coding: utf-8 -*-
"""Тесты проводки ObservabilityStore в drain-петлю процесса (Ф5.20a)."""

from __future__ import annotations

from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityHub,
    ObservabilityStore,
)
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    STORE_ERROR_TAP,
    drain_process_observability,
    unwire_observability_store,
    wire_observability_store,
)


class FakeErrorManager:
    """Мини-LoggerCore: реестр tap'ов + эмиссия error через них."""

    def __init__(self):
        self._taps = {}

    def add_log_tap(self, channel, *, min_level="ERROR", name=None):
        self._taps[name or channel.name] = channel
        return name or channel.name

    def remove_log_tap(self, name):
        return self._taps.pop(name, None) is not None

    def emit_error(self, message, module="worker_module", level="ERROR"):
        rec = {"timestamp": 1.0, "level": level, "scope": "system", "message": message, "module": module, "extra": {}}
        for ch in list(self._taps.values()):
            ch.write(rec)


class TestWireStore:
    def test_wire_creates_store_and_error_tap(self, tmp_path):
        err = FakeErrorManager()
        store, tap = wire_observability_store(err, db_path=str(tmp_path / "obs.db"))
        assert isinstance(store, ObservabilityStore)
        assert tap == STORE_ERROR_TAP
        assert STORE_ERROR_TAP in err._taps
        store.close()

    def test_error_emission_reaches_store_via_tap(self, tmp_path):
        """Write-through error (мимо hub) попадает в стор через tap."""
        err = FakeErrorManager()
        store, _ = wire_observability_store(err, db_path=str(tmp_path / "obs.db"))
        err.emit_error("crash-1")
        err.emit_error("crash-2", level="CRITICAL")
        rows = store.list_records(kind="error")
        assert [r["message"] for r in rows] == ["crash-2", "crash-1"]
        assert rows[0]["severity"] == "critical"
        store.close()

    def test_wire_without_error_manager(self, tmp_path):
        store, tap = wire_observability_store(None, db_path=str(tmp_path / "obs.db"))
        assert isinstance(store, ObservabilityStore)
        assert tap is None
        store.close()

    def test_unwire_removes_tap(self, tmp_path):
        err = FakeErrorManager()
        store, tap = wire_observability_store(err, db_path=str(tmp_path / "obs.db"))
        unwire_observability_store(err, store, tap)
        assert STORE_ERROR_TAP not in err._taps


class TestDrainToStore:
    def test_drain_persists_log_and_stats_not_error(self, tmp_path):
        hub = ObservabilityHub("worker_module")
        hub.info("hello")
        hub.record_metric("fps", 30)
        # error в hub НЕ кладём — он идёт write-through; но проверим, что даже
        # если бы попал, drain его в стор НЕ пишет (источник error — tap).
        store = ObservabilityStore(str(tmp_path / "obs.db"))

        drain_process_observability(hub, None, store)

        assert store.count(kind="log") == 1
        assert store.count(kind="stats") == 1
        assert store.count(kind="error") == 0
        assert store.list_records(kind="log")[0]["message"] == "hello"
        assert store.list_records(kind="stats")[0]["message"] == "fps"
        store.close()

    def test_drain_all_called_once_empties_hub(self, tmp_path):
        hub = ObservabilityHub("worker_module")
        hub.info("once")
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        drain_process_observability(hub, None, store)
        # Второй drain — каналы уже осушены, стор не растёт.
        drain_process_observability(hub, None, store)
        assert store.count(kind="log") == 1
        store.close()

    def test_drain_store_none_is_noop_safe(self, tmp_path):
        hub = ObservabilityHub("worker_module")
        hub.info("x")
        drain_process_observability(hub, None, None)  # без стора — не падает
