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

    def test_traced_decorator_records_per_item(self, trace_on) -> None:
        """traced меряет вызов и делит на батч → честное per-item время."""

        class _Fake:
            name = "blur"
            _trace_node = "detector"

            @frame_trace.traced
            def process(self, items):
                return [{**it} for it in items]

        out = _Fake().process([{"id": 1}, {"id": 2}])
        # Каждый выходной item получил свой process-спан blur@detector.
        for it in out:
            assert it["trace"][-1]["kind"] == "process"
            assert it["trace"][-1]["plugin"] == "blur"
            assert it["trace"][-1]["node"] == "detector"

    def test_traced_decorator_noop_when_disabled(self, trace_off) -> None:
        class _Fake:
            name = "blur"

            @frame_trace.traced
            def process(self, items):
                return [{**it} for it in items]

        out = _Fake().process([{"id": 1}])
        assert "trace" not in out[0]

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


class TestInstallTracing:
    """C6 рычаг 2: обёртка process/produce на бутe (не в __init_subclass__)."""

    def test_wraps_process_and_produce(self) -> None:
        class _Plug:
            name = "blur"
            _trace_node = "detector"

            def process(self, items):
                return [{**it} for it in items]

            def produce(self):
                return [{"src": 1}]

        assert not getattr(_Plug.process, "_traced", False)
        frame_trace.install_tracing(_Plug)
        assert getattr(_Plug.process, "_traced", False) is True
        assert getattr(_Plug.produce, "_traced", False) is True

    def test_idempotent(self) -> None:
        class _Plug:
            name = "blur"
            _trace_node = "detector"

            def process(self, items):
                return items

        frame_trace.install_tracing(_Plug)
        wrapped = _Plug.process
        frame_trace.install_tracing(_Plug)  # повторный бут того же класса
        assert _Plug.process is wrapped  # не обёрнут дважды

    def test_traces_after_install(self, trace_on) -> None:
        class _Plug:
            name = "blur"
            _trace_node = "detector"

            def process(self, items):
                return [{**it} for it in items]

        frame_trace.install_tracing(_Plug)
        out = _Plug().process([{"id": 1}])
        assert out[0]["trace"][-1]["plugin"] == "blur"
        assert out[0]["trace"][-1]["node"] == "detector"

    def test_no_method_no_error(self) -> None:
        class _Plug:
            name = "empty"

        frame_trace.install_tracing(_Plug)  # нет process/produce — no-op
