# -*- coding: utf-8 -*-
"""Тесты Ф1 Task 1.5: log tap + RouterPushChannel (tail логов ≥ level).

- LoggerManager.add_log_tap: КАЖДАЯ запись ≥ порога уходит в tap-sink; ниже — нет;
- tap переживает reconfigure() (подписка на tail не рвётся при hot-reload);
- RouterPushChannel.write: пушит запись адресным router-сообщением (мост 1.1b).
"""

from __future__ import annotations

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.logger_module.channels.router_push_channel import RouterPushChannel


class _CollectSink:
    """Tap-sink: собирает полученные записи (IChannel-совместим)."""

    def __init__(self, name: str = "collect") -> None:
        self._name = name
        self.records: list = []

    @property
    def name(self) -> str:
        return self._name

    def write(self, data: dict) -> dict:
        self.records.append(data)
        return {"status": "success", "channel": self._name}

    def close(self) -> None:
        pass


class _FakeRouter:
    def __init__(self) -> None:
        self.sent: list = []

    def send_async(self, message: dict, priority: str = "normal") -> None:
        self.sent.append((message, priority))


class TestLogTap:
    def test_tap_receives_error_not_info(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        sink = _CollectSink()
        mgr.add_log_tap(sink, min_level="ERROR")

        mgr.error("boom", module="test")
        mgr.info("noise", module="test")

        assert len(sink.records) == 1
        assert sink.records[0]["level"] == "ERROR"
        assert sink.records[0]["message"] == "boom"

    def test_tap_threshold_warning_includes_error(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        sink = _CollectSink()
        mgr.add_log_tap(sink, min_level="WARNING")

        mgr.warning("w", module="test")
        mgr.error("e", module="test")
        mgr.info("i", module="test")

        levels = [r["level"] for r in sink.records]
        assert levels == ["WARNING", "ERROR"]

    def test_remove_tap_stops_delivery(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        sink = _CollectSink()
        name = mgr.add_log_tap(sink, min_level="ERROR")
        assert mgr.remove_log_tap(name) is True

        mgr.error("after-remove", module="test")
        assert sink.records == []
        assert mgr.remove_log_tap(name) is False  # уже нет

    def test_tap_survives_reconfigure(self) -> None:
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        sink = _CollectSink()
        mgr.add_log_tap(sink, min_level="ERROR")

        # reconfigure закрывает каналы реестра, но tap живёт отдельно.
        assert mgr.reconfigure({"default_level": "DEBUG"}) is True
        mgr.error("after-reconfigure", module="test")
        assert len(sink.records) == 1


class TestRouterPushChannel:
    def test_write_pushes_addressed_message(self) -> None:
        router = _FakeRouter()
        ch = RouterPushChannel("log_tail::backend_ctl", router=router, subscriber="backend_ctl", sender="preprocessor")
        res = ch.write({"level": "ERROR", "message": "boom"})

        assert res["status"] == "success"
        assert len(router.sent) == 1
        msg, priority = router.sent[0]
        assert msg["targets"] == ["backend_ctl"]
        assert msg["queue_type"] == "system"
        assert msg["command"] == "log.record"
        assert msg["type"] == "event"
        assert msg["data"]["record"]["message"] == "boom"
        assert msg["data"]["process"] == "preprocessor"

    def test_write_without_router_is_error_not_raise(self) -> None:
        ch = RouterPushChannel("t", router=None, subscriber="backend_ctl")
        res = ch.write({"level": "ERROR"})
        assert res["status"] == "error"

    def test_end_to_end_tap_pushes_error(self) -> None:
        """LoggerManager.error → tap(RouterPushChannel) → router.send_async."""
        mgr = LoggerManager(manager_name="TapTest")
        mgr.initialize()
        router = _FakeRouter()
        mgr.add_log_tap(
            RouterPushChannel("log_tail::backend_ctl", router=router, subscriber="backend_ctl", sender="proc"),
            min_level="ERROR",
        )
        mgr.error("kaboom", module="test")

        assert len(router.sent) == 1
        assert router.sent[0][0]["data"]["record"]["message"] == "kaboom"
