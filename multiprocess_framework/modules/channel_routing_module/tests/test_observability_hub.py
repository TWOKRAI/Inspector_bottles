# -*- coding: utf-8 -*-
"""
Contract-тесты ObservabilityHub (Ф5.15).

Покрывают acceptance: эмиссия→нужный канал; overflow→счётчик потерь растёт;
drain опустошает; severity/context не теряются; записи pickle-safe (Dict at
Boundary); Protocol-соответствие слотам; non-destructive мониторинг; и ключевое —
drop-in в ObservableMixin без правок модулей (в т.ч. без двойной записи ошибки).
"""

import pickle

import pytest

from ..observability import (
    KIND_ERROR,
    KIND_LOG,
    KIND_STATS,
    METRIC_COUNTER,
    METRIC_GAUGE,
    METRIC_TIMING,
    ErrorLike,
    LoggerLike,
    ObservabilityHub,
    StatsLike,
)


class _Clock:
    """Детерминированный источник времени для тестов."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        self.t += 1.0
        return self.t


@pytest.fixture
def hub() -> ObservabilityHub:
    return ObservabilityHub("worker_module", capacity=8, clock=_Clock())


class TestEmissionRouting:
    def test_log_goes_only_to_log_channel(self, hub):
        hub.info("hello", user="bob")
        logs = hub.drain_logs()
        assert len(logs) == 1
        rec = logs[0]
        assert rec["kind"] == KIND_LOG
        assert rec["module"] == "worker_module"
        assert rec["severity"] == "info"
        assert rec["message"] == "hello"
        assert rec["context"] == {"user": "bob"}
        assert "ts" in rec
        assert hub.drain_errors() == []
        assert hub.drain_stats() == []

    def test_all_log_levels(self, hub):
        for lvl in ("debug", "info", "warning", "error", "critical"):
            getattr(hub, lvl)(f"m-{lvl}")
        assert [r["severity"] for r in hub.drain_logs()] == [
            "debug",
            "info",
            "warning",
            "error",
            "critical",
        ]

    def test_generic_log(self, hub):
        hub.log("notice", "custom-level")
        rec = hub.drain_logs()[0]
        assert rec["severity"] == "notice"

    def test_stats_metric_types(self, hub):
        hub.record_metric("m1", 5)
        hub.increment("m2")
        hub.record_timing("m3", 0.42)
        hub.gauge("m4", 7)
        by = {r["metric"]: r for r in hub.drain_stats()}
        assert by["m1"]["metric_type"] == METRIC_GAUGE
        assert by["m2"]["metric_type"] == METRIC_COUNTER
        assert by["m3"]["metric_type"] == METRIC_TIMING and by["m3"]["value"] == 0.42
        assert by["m4"]["metric_type"] == METRIC_GAUGE and by["m4"]["value"] == 7
        assert all(r["kind"] == KIND_STATS for r in by.values())

    def test_error_serialized_to_error_channel(self, hub):
        try:
            raise ValueError("boom")
        except ValueError as exc:
            hub.track_error(exc, {"module": "sub"})
        errs = hub.drain_errors()
        assert len(errs) == 1
        rec = errs[0]
        assert rec["kind"] == KIND_ERROR
        assert rec["error_type"] == "ValueError"
        assert rec["message"] == "boom"
        assert rec["traceback"] and "ValueError: boom" in rec["traceback"]
        assert rec["context"] == {"module": "sub"}
        assert rec["severity"] == "error"


class TestSeverityContext:
    def test_error_severity_override_from_context(self, hub):
        hub.track_error(RuntimeError("x"), {"severity": "critical", "op": "flush"})
        rec = hub.drain_errors()[0]
        assert rec["severity"] == "critical"
        assert rec["context"] == {"op": "flush"}  # severity извлечён, остальное цело

    def test_error_without_traceback(self, hub):
        hub.track_error(KeyError("k"))  # без raise → нет __traceback__
        rec = hub.drain_errors()[0]
        assert rec["error_type"] == "KeyError"
        assert rec["traceback"] is None


class TestOverflow:
    def test_overflow_increments_loss_counter(self, hub):
        for i in range(20):  # capacity=8
            hub.info(f"m{i}")
        assert hub.dropped[KIND_LOG] == 12
        assert len(hub.drain_logs()) == 8  # накопленные последние 8
        assert hub.dropped[KIND_LOG] == 12  # счётчик монотонный, дренаж не сбрасывает


class TestDrain:
    def test_drain_empties(self, hub):
        hub.info("a")
        assert len(hub.drain_logs()) == 1
        assert hub.drain_logs() == []

    def test_drain_all(self, hub):
        hub.info("a")
        hub.increment("c")
        hub.track_error(ValueError("e"))
        allrec = hub.drain_all()
        assert len(allrec[KIND_LOG]) == 1
        assert len(allrec[KIND_STATS]) == 1
        assert len(allrec[KIND_ERROR]) == 1
        assert hub.drain_all() == {KIND_LOG: [], KIND_ERROR: [], KIND_STATS: []}


class TestPickleSafe:
    def test_all_records_pickle_roundtrip(self, hub):
        hub.info("log", k=1)
        hub.record_metric("m", 3, {"t": "x"})
        try:
            raise ValueError("boom")
        except ValueError as exc:
            hub.track_error(exc, {"c": 1})
        for rec in [*hub.drain_logs(), *hub.drain_stats(), *hub.drain_errors()]:
            assert pickle.loads(pickle.dumps(rec)) == rec


class TestProtocols:
    def test_hub_satisfies_all_three_slots(self, hub):
        assert isinstance(hub, LoggerLike)
        assert isinstance(hub, StatsLike)
        assert isinstance(hub, ErrorLike)


class TestMonitorPlane:
    def test_get_info_non_destructive(self, hub):
        hub.info("a")
        hub.info("b")
        hub.increment("c")
        info = hub.get_info()
        assert info["module"] == "worker_module"
        assert info["channels"][KIND_LOG]["depth"] == 2
        assert info["channels"][KIND_STATS]["depth"] == 1
        assert len(hub.drain_logs()) == 2  # мониторинг не съел записи


class TestObservableMixinDropIn:
    """Ноль правок внутри модулей: hub подставляется в слоты ObservableMixin."""

    def _make_manager(self, hub):
        from ...base_manager.mixins.observable_mixin import ObservableMixin

        class _Mgr(ObservableMixin):
            def __init__(self, sink):
                ObservableMixin.__init__(
                    self,
                    managers={"logger": sink, "stats": sink, "error": sink},
                    config={"logger": True, "stats": True, "error": True},
                )

        return _Mgr(hub)

    def test_log_metric_error_flow_through_hub(self, hub):
        mgr = self._make_manager(hub)
        mgr._log_info("via mixin")
        mgr._record_metric("ops", 2)
        mgr._track_error(ValueError("bad"), {"where": "unit"})

        assert len(hub.drain_logs()) == 1
        assert len(hub.drain_stats()) == 1
        errs = hub.drain_errors()
        # КЛЮЧЕВОЕ: ровно ОДНА запись — track_error не свалился в fallback record_error
        assert len(errs) == 1
        assert errs[0]["error_type"] == "ValueError"
        assert errs[0]["context"] == {"where": "unit"}
