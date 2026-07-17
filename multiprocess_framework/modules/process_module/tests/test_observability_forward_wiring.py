# -*- coding: utf-8 -*-
"""Тесты проводки live-хвоста наблюдаемости hub→подписчик (Ф5.20b, F1: per-subscriber).

Симметрично store-wiring (Ф5.20a), но приёмник — router-push на подписчика, а не
SQLite. Контракт: log/stats — пачкой из drain-петли, error/critical — по одной у
tap'а на error+logger менеджерах (write-through), всё command=observability.record.

F1: имена tap'ов/каналов keyed по subscriber → несколько подписчиков (GUI + backend_ctl)
держат независимые форвардеры на одном процессе. drain фан-аутит пачку каждому.
"""

from __future__ import annotations

from multiprocess_framework.modules.channel_routing_module.observability import ObservabilityHub
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    drain_process_observability,
    forward_tap_names,
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
    def test_wire_installs_per_subscriber_taps_on_both_managers(self):
        err, log = FakeLoggerCore(), FakeLoggerCore()
        router = FakeRouter()
        _, error_name, logger_name = forward_tap_names("gui")
        _, taps = wire_observability_forward(router, "gui", "cam", log, err)
        assert {name for _, name in taps} == {error_name, logger_name}
        assert error_name in err._taps
        assert logger_name in log._taps

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
        _, error_name, logger_name = forward_tap_names("gui")
        _, taps = wire_observability_forward(FakeRouter(), "gui", "cam", log, err)
        unwire_observability_forward(taps)
        assert error_name not in err._taps
        assert logger_name not in log._taps


class TestPerSubscriberIndependence:
    """F1: два подписчика на одном процессе — независимые форвардеры и tap'ы."""

    def test_two_subscribers_have_distinct_tap_names(self):
        # Регресс F1: имена tap'ов ДОЛЖНЫ отличаться по подписчику, иначе один слот
        # угоняет реестр tap'ов у другого (единственный форвардер на процесс).
        err = FakeLoggerCore()
        wire_observability_forward(FakeRouter(), "gui", "cam", None, err)
        wire_observability_forward(FakeRouter(), "backend_ctl", "cam", None, err)
        _, gui_err, _ = forward_tap_names("gui")
        _, bc_err, _ = forward_tap_names("backend_ctl")
        assert gui_err in err._taps
        assert bc_err in err._taps
        assert gui_err != bc_err  # разные подписчики → разные tap'ы

    def test_error_fans_out_to_both_subscribers(self):
        # Одна error-эмиссия ловится ОБОИМИ tap'ами → пуш каждому подписчику.
        err = FakeLoggerCore()
        gui_router, bc_router = FakeRouter(), FakeRouter()
        wire_observability_forward(gui_router, "gui", "cam", None, err)
        wire_observability_forward(bc_router, "backend_ctl", "cam", None, err)
        err.emit_error("boom", level="ERROR")
        assert [m["targets"] for m in gui_router.sent] == [["gui"]]
        assert [m["targets"] for m in bc_router.sent] == [["backend_ctl"]]

    def test_unsubscribe_one_does_not_break_other(self):
        # Регресс F1: снятие tap'а одного подписчика НЕ должно ронять хвост другого.
        err = FakeLoggerCore()
        gui_router, bc_router = FakeRouter(), FakeRouter()
        wire_observability_forward(gui_router, "gui", "cam", None, err)
        wire_observability_forward(bc_router, "backend_ctl", "cam", None, err)
        # backend_ctl отписывается — снимаем ЕГО tap'ы (у него свои имена).
        _, bc_error, bc_logger = forward_tap_names("backend_ctl")
        unwire_observability_forward([(err, bc_error), (err, bc_logger)])
        err.emit_error("still-alive", level="ERROR")
        # GUI по-прежнему получает записи, backend_ctl — нет.
        assert len(gui_router.sent) == 1
        assert bc_router.sent == []


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

    def test_drain_fans_out_batch_to_all_subscribers(self):
        # F1: пачка уходит КАЖДОМУ форвардеру, буфер дренируется РОВНО один раз.
        hub = ObservabilityHub("worker_module")
        hub.info("hi")
        hub.record_metric("fps", 15)
        gui_router, bc_router = FakeRouter(), FakeRouter()
        gui_fwd, _ = wire_observability_forward(gui_router, "gui", "worker_module", None, None)
        bc_fwd, _ = wire_observability_forward(bc_router, "backend_ctl", "worker_module", None, None)

        drain_process_observability(hub, None, None, [gui_fwd, bc_fwd])

        assert len(gui_router.sent) == 1
        assert len(bc_router.sent) == 1
        # Буфер дренирован один раз: повторный drain — пусто, никто не получает.
        drain_process_observability(hub, None, None, [gui_fwd, bc_fwd])
        assert len(gui_router.sent) == 1
        assert len(bc_router.sent) == 1

    def test_drain_forwarder_none_is_noop_safe(self):
        hub = ObservabilityHub("worker_module")
        hub.info("x")
        drain_process_observability(hub, None, None, None)  # без форвардеров — не падает

    def test_drain_empty_no_push(self):
        hub = ObservabilityHub("worker_module")
        router = FakeRouter()
        forwarder, _ = wire_observability_forward(router, "gui", "worker_module", None, None)
        drain_process_observability(hub, None, None, forwarder)
        assert router.sent == []  # пусто → нет пуша
