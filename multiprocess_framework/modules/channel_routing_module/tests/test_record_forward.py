# -*- coding: utf-8 -*-
"""Тесты live-форвардинга записей наблюдаемости hub→GUI (Ф5.20b).

Покрывает нормализацию (record_display) и push-канал (RecordForwardChannel):
единый display-вид из двух источников (hub-запись / LogRecord-dict) и форма
адресного пуша ``command="observability.record"``.
"""

from __future__ import annotations

from ..observability import (
    FORWARD_COMMAND,
    RecordForwardChannel,
    hub_record_to_display,
    log_record_to_display,
)


class FakeRouter:
    """Мок-роутер: копит отправленные send_async сообщения."""

    def __init__(self):
        self.sent = []

    def send_async(self, message, priority="normal"):
        self.sent.append((message, priority))


# ---------------------------------------------------------------------------
# Нормализация в display-вид
# ---------------------------------------------------------------------------


def test_hub_log_record_to_display():
    rec = {"kind": "log", "module": "worker", "ts": 1.5, "severity": "INFO", "message": "hi", "context": {"a": 1}}
    d = hub_record_to_display(rec)
    assert d == {
        "kind": "log",
        "module": "worker",
        "ts": 1.5,
        "severity": "info",  # нормализуется в lower
        "message": "hi",
        "extra": {"context": {"a": 1}},
    }


def test_hub_stats_record_to_display():
    rec = {"kind": "stats", "module": "worker", "ts": 2.0, "metric": "fps", "value": 30, "metric_type": "gauge"}
    d = hub_record_to_display(rec)
    assert d["kind"] == "stats"
    assert d["message"] == "fps"  # message = metric
    assert d["severity"] == "gauge"  # severity = metric_type
    assert d["extra"] == {"value": 30, "tags": {}}


def test_log_record_dict_to_display_defaults_error():
    rec = {"timestamp": 3.0, "level": "CRITICAL", "scope": "system", "message": "boom", "module": "cam", "extra": {}}
    d = log_record_to_display(rec)
    assert d == {"kind": "error", "module": "cam", "ts": 3.0, "severity": "critical", "message": "boom", "extra": {}}


# ---------------------------------------------------------------------------
# RecordForwardChannel — форма пуша
# ---------------------------------------------------------------------------


def test_write_pushes_single_error_record():
    router = FakeRouter()
    ch = RecordForwardChannel(router=router, subscriber="gui", sender="cam", name="fwd")
    rec = {"timestamp": 1.0, "level": "ERROR", "message": "x", "module": "cam", "extra": {}}
    res = ch.write(rec)
    assert res["status"] == "success"
    assert len(router.sent) == 1
    msg, prio = router.sent[0]
    assert msg["command"] == FORWARD_COMMAND
    assert msg["targets"] == ["gui"]
    assert msg["queue_type"] == "system"
    assert msg["type"] == "event"
    assert msg["data"]["process"] == "cam"
    assert msg["data"]["record"]["message"] == "x"
    assert msg["data"]["record"]["kind"] == "error"


def test_push_batch_sends_records_list():
    router = FakeRouter()
    ch = RecordForwardChannel(router=router, subscriber="gui", sender="cam")
    records = [
        {"kind": "log", "module": "cam", "ts": 1.0, "severity": "info", "message": "a", "extra": {}},
        {"kind": "stats", "module": "cam", "ts": 2.0, "severity": "gauge", "message": "fps", "extra": {}},
    ]
    ch.push_batch(records)
    assert len(router.sent) == 1
    msg, _ = router.sent[0]
    assert [r["message"] for r in msg["data"]["records"]] == ["a", "fps"]


def test_push_batch_empty_is_noop():
    router = FakeRouter()
    ch = RecordForwardChannel(router=router, subscriber="gui", sender="cam")
    res = ch.push_batch([])
    assert res["sent"] == 0
    assert router.sent == []


def test_push_router_none_returns_error_no_raise():
    ch = RecordForwardChannel(router=None, subscriber="gui", sender="cam")
    res = ch.write({"timestamp": 1.0, "level": "ERROR", "message": "x", "module": "cam"})
    assert res["status"] == "error"
    assert res["reason"] == "router=None"
