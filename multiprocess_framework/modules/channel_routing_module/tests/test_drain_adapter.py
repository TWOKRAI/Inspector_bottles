# -*- coding: utf-8 -*-
"""
Контракт-тесты ObservabilityDrainAdapter (Ф5.16 a).

Прогоняем реальные записи через ObservabilityHub → drain → adapter → mock-sink,
проверяя severity/metric_type-роутинг и паритет вызова с прямым путём.
"""

from ..observability.drain_adapter import ObservabilityDrainAdapter
from ..observability.observability_hub import ObservabilityHub


class RecordingSink:
    """Мок-sink: записывает (method, args, kwargs) каждого вызова."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        # Любой вызванный метод перехватывается и логируется.
        def _rec(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _rec


def _hub():
    return ObservabilityHub("mod", capacity=64, clock=lambda: 111.0)


# ---------------------------------------------------------------------------
# apply_log — severity-роутинг
# ---------------------------------------------------------------------------


def test_apply_log_routes_by_severity():
    hub = _hub()
    hub.warning("disk low", disk="sda")
    rec = hub.drain_logs()[0]

    logger = RecordingSink()
    adapter = ObservabilityDrainAdapter(logger=logger)
    assert adapter.apply_log(rec) is True

    assert len(logger.calls) == 1
    method, args, kwargs = logger.calls[0]
    assert method == "warning"
    assert args[0] == "disk low"
    assert kwargs.get("disk") == "sda"


def test_apply_log_unknown_severity_falls_back_to_info():
    adapter = ObservabilityDrainAdapter(logger=RecordingSink())
    logger = adapter._logger
    adapter.apply_log({"severity": "trace", "message": "m", "context": {}})
    assert logger.calls[0][0] == "info"


def test_apply_log_no_sink_returns_false():
    adapter = ObservabilityDrainAdapter(logger=None)
    assert adapter.apply_log({"severity": "info", "message": "m", "context": {}}) is False


# ---------------------------------------------------------------------------
# apply_error — severity-роутинг ErrorManager воспроизводится
# ---------------------------------------------------------------------------


def test_apply_error_routes_severity_and_builds_message():
    hub = _hub()
    hub.track_error(ValueError("boom"), {"severity": "critical", "module": "svc"})
    rec = hub.drain_errors()[0]

    error = RecordingSink()
    adapter = ObservabilityDrainAdapter(error=error)
    assert adapter.apply_error(rec) is True

    method, args, kwargs = error.calls[0]
    assert method == "critical"
    assert "ValueError" in args[0] and "boom" in args[0]
    assert kwargs.get("module") == "svc"


def test_apply_error_default_severity_is_error():
    hub = _hub()
    hub.track_error(RuntimeError("x"))
    rec = hub.drain_errors()[0]

    error = RecordingSink()
    ObservabilityDrainAdapter(error=error).apply_error(rec)
    assert error.calls[0][0] == "error"


# ---------------------------------------------------------------------------
# apply_stat — роутинг по metric_type
# ---------------------------------------------------------------------------


def test_apply_stat_counter_timing_gauge():
    hub = _hub()
    hub.increment("hits", 3)
    hub.record_timing("lat", 0.5)
    hub.gauge("temp", 42)
    logs = hub.drain_stats()

    stats = RecordingSink()
    adapter = ObservabilityDrainAdapter(stats=stats)
    for rec in logs:
        adapter.apply_stat(rec)

    methods = [c[0] for c in stats.calls]
    assert methods == ["record_metric", "record_timing", "gauge"]
    # значение и tags доходят до sink'а
    assert stats.calls[0][1][0] == "hits" and stats.calls[0][1][1] == 3
    assert stats.calls[1][1][1] == 0.5
    assert stats.calls[2][1][1] == 42


def test_apply_stat_unknown_type_falls_back_to_record_metric():
    stats = RecordingSink()
    adapter = ObservabilityDrainAdapter(stats=stats)
    adapter.apply_stat({"metric": "m", "value": 7, "metric_type": "weird", "tags": {}})
    assert stats.calls[0][0] == "record_metric"


# ---------------------------------------------------------------------------
# apply_drained — пакет
# ---------------------------------------------------------------------------


def test_apply_drained_dispatches_all_kinds():
    hub = _hub()
    hub.info("l")
    hub.track_error(ValueError("e"))
    hub.increment("c")

    logger, stats, error = RecordingSink(), RecordingSink(), RecordingSink()
    adapter = ObservabilityDrainAdapter(logger=logger, stats=stats, error=error)
    adapter.apply_drained(hub.drain_all())

    assert logger.calls and error.calls and stats.calls


# ---------------------------------------------------------------------------
# Паритет: adapter бьёт в тот же метод, что и прямой путь ObservableMixin
# ---------------------------------------------------------------------------


def test_parity_log_call_matches_direct_path():
    """Прямой путь: sink.warning('m', k=v). Hub-путь → drain → adapter → тот же вызов."""
    direct = RecordingSink()
    direct.warning("m", k="v")

    hub = _hub()
    hub.warning("m", k="v")
    via_hub = RecordingSink()
    ObservabilityDrainAdapter(logger=via_hub).apply_log(hub.drain_logs()[0])

    assert direct.calls[0] == via_hub.calls[0]
