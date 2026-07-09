# -*- coding: utf-8 -*-
"""Тесты проводки live-хвоста наблюдаемости hub→GUI (Ф5.20b).

Симметрично store-wiring (Ф5.20a), но приёмник — router-push на GUI-подписчика,
а не SQLite. Контракт: log/stats — пачкой из drain-петли, error/critical — по
одной у tap'а на error+logger менеджерах (write-through), всё command=observability.record.
"""

from __future__ import annotations

from multiprocess_framework.modules.channel_routing_module.observability import ObservabilityHub
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    FORWARD_ERROR_TAP,
    FORWARD_LOGGER_TAP,
    drain_process_observability,
    unwire_observability_forward,
    wire_observability_forward,
)


class FakeRouter:
    def __init__(self):
        self.sent = []

    def send_async(self, message, priority="normal"):
        self.sent.append(message)


class FakeLoggerCore:
    """Мини-LoggerCore: реестр tap'ов + эмиссия error-записи через них."""

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


class TestWireForward:
    def test_wire_installs_taps_on_both_managers(self):
        err, log = FakeLoggerCore(), FakeLoggerCore()
        router = FakeRouter()
        _, taps = wire_observability_forward(router, "gui", "cam", log, err)
        assert {name for _, name in taps} == {FORWARD_ERROR_TAP, FORWARD_LOGGER_TAP}
        assert FORWARD_ERROR_TAP in err._taps
        assert FORWARD_LOGGER_TAP in log._taps

    def test_error_via_manager_pushed_to_subscriber(self):
        err = FakeLoggerCore()
        router = FakeRouter()
        wire_observability_forward(router, "gui", "cam", None, err)
        err.emit_error("crash", level="CRITICAL")
        assert len(router.sent) == 1
        msg = router.sent[0]
        assert msg["command"] == "observability.record"
        assert msg["targets"] == ["gui"]
        assert msg["data"]["record"]["kind"] == "error"
        assert msg["data"]["record"]["severity"] == "critical"
        assert msg["data"]["record"]["message"] == "crash"

    def test_wire_without_managers_forwarder_still_works(self):
        router = FakeRouter()
        forwarder, taps = wire_observability_forward(router, "gui", "cam", None, None)
        assert taps == []
        forwarder([{"kind": "log", "module": "cam", "ts": 1.0, "severity": "info", "message": "m"}])
        assert len(router.sent) == 1

    def test_unwire_removes_taps(self):
        err, log = FakeLoggerCore(), FakeLoggerCore()
        _, taps = wire_observability_forward(FakeRouter(), "gui", "cam", log, err)
        unwire_observability_forward(taps)
        assert FORWARD_ERROR_TAP not in err._taps
        assert FORWARD_LOGGER_TAP not in log._taps


class TestDrainForward:
    def test_drain_forwards_log_and_stats_batch(self):
        hub = ObservabilityHub("worker_module")
        hub.info("hello")
        hub.record_metric("fps", 30)
        router = FakeRouter()
        forwarder, _ = wire_observability_forward(router, "gui", "worker_module", None, None)

        drain_process_observability(hub, None, None, forwarder)

        assert len(router.sent) == 1  # одна пачка
        records = router.sent[0]["data"]["records"]
        kinds = sorted(r["kind"] for r in records)
        assert kinds == ["log", "stats"]

    def test_drain_forwarder_none_is_noop_safe(self):
        hub = ObservabilityHub("worker_module")
        hub.info("x")
        drain_process_observability(hub, None, None, None)  # без форвардера — не падает

    def test_drain_empty_no_push(self):
        hub = ObservabilityHub("worker_module")
        router = FakeRouter()
        forwarder, _ = wire_observability_forward(router, "gui", "worker_module", None, None)
        drain_process_observability(hub, None, None, forwarder)
        assert router.sent == []  # пусто → нет пуша
