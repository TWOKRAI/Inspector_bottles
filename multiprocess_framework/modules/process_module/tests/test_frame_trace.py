# -*- coding: utf-8 -*-
"""Тесты frame_trace — пер-сегментная трассировка кадра (in-band)."""

import pytest

from multiprocess_framework.modules.process_module.generic import frame_trace


@pytest.fixture
def trace_on():
    """Включить трассировку на время теста (env читается при импорте)."""
    prev = frame_trace._ENABLED
    frame_trace._ENABLED = True
    yield
    frame_trace._ENABLED = prev


@pytest.fixture
def trace_off():
    prev = frame_trace._ENABLED
    frame_trace._ENABLED = False
    yield
    frame_trace._ENABLED = prev


class TestDisabled:
    def test_noop_when_disabled(self, trace_off) -> None:
        item: dict = {}
        frame_trace.stamp_send(item, "camera_0")
        frame_trace.record_transport(item, "detector")
        frame_trace.record_process(item, "detector", "hsv_mask", 1.0)
        assert item == {}  # ничего не добавлено


class TestEnabled:
    def test_stamp_send_sets_fields(self, trace_on) -> None:
        item: dict = {}
        frame_trace.stamp_send(item, "camera_0")
        assert item["_from"] == "camera_0"
        assert isinstance(item["_t_send"], float)

    def test_transport_span_from_stamp(self, trace_on) -> None:
        item: dict = {}
        frame_trace.stamp_send(item, "camera_0")
        frame_trace.record_transport(item, "detector")
        # Служебные поля сняты, transport-спан добавлен.
        assert "_t_send" not in item and "_from" not in item
        assert len(item["trace"]) == 1
        span = item["trace"][0]
        assert span["kind"] == "transport"
        assert span["from"] == "camera_0"
        assert span["to"] == "detector"
        assert span["ms"] >= 0.0

    def test_transport_noop_without_stamp(self, trace_on) -> None:
        item: dict = {}
        frame_trace.record_transport(item, "detector")
        assert "trace" not in item  # нечего считать — отметки отправки не было

    def test_process_span(self, trace_on) -> None:
        item: dict = {}
        frame_trace.record_process(item, "detector", "hsv_mask", 0.6)
        assert item["trace"] == [{"kind": "process", "node": "detector", "plugin": "hsv_mask", "ms": 0.6}]

    def test_full_chain_accumulates(self, trace_on) -> None:
        """Полный путь: source→detector→painter→gui накапливает спаны по порядку."""
        item: dict = {}
        frame_trace.record_process(item, "camera_0", "webcam", 2.0)
        frame_trace.stamp_send(item, "camera_0")
        frame_trace.record_transport(item, "detector")
        frame_trace.record_process(item, "detector", "hsv_mask", 0.6)
        frame_trace.stamp_send(item, "detector")
        frame_trace.record_transport(item, "painter")
        kinds = [(s["kind"], s.get("plugin") or f"{s.get('from')}->{s.get('to')}") for s in item["trace"]]
        assert kinds == [
            ("process", "webcam"),
            ("transport", "camera_0->detector"),
            ("process", "hsv_mask"),
            ("transport", "detector->painter"),
        ]
