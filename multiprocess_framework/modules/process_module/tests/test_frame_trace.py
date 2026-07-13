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


class TestInstallTracingInheritance:
    """Fable MED-3: обход mro — наследник без переопределения process() тоже трассируется."""

    def test_inherited_process_wrapped_on_owner(self, trace_on) -> None:
        from multiprocess_framework.modules.process_module.plugins.base import (
            ProcessModulePlugin,
        )

        class _Base(ProcessModulePlugin):
            name = "base"

            def configure(self, ctx):  # ProcessModulePlugin.configure абстрактный
                return None

            def process(self, items):
                return [{**it} for it in items]

        class _Child(_Base):  # НЕ переопределяет process
            name = "child"

        frame_trace.install_tracing(_Child)
        # обёрнут метод-владелец на _Base (общий для потомков)
        assert getattr(_Base.__dict__["process"], "_traced", False) is True
        out = _Child().process([{"id": 1}])
        assert out[0]["trace"][-1]["kind"] == "process"

    def test_base_default_process_not_wrapped(self) -> None:
        """Дефолтные process/produce самого ProcessModulePlugin НЕ оборачиваются."""
        from multiprocess_framework.modules.process_module.plugins.base import (
            ProcessModulePlugin,
        )

        class _Plain(ProcessModulePlugin):
            name = "plain"  # без переопределения process/produce

        frame_trace.install_tracing(_Plain)
        assert not getattr(ProcessModulePlugin.__dict__["process"], "_traced", False)
        assert not getattr(ProcessModulePlugin.__dict__["produce"], "_traced", False)


class TestTraceId:
    """Ф7 G.6: trace_id — семантическое поле корреляции лог↔кадр, ВСЕГДА активно
    (в отличие от span-трассировки выше — не гейтится INSPECTOR_FRAME_TRACE)."""

    def test_new_trace_id_format(self) -> None:
        """32 hex-символа — формат W3C trace-context trace-id (128 бит)."""
        trace_id = frame_trace.new_trace_id()
        assert len(trace_id) == 32
        assert all(c in "0123456789abcdef" for c in trace_id)

    def test_new_trace_id_unique(self) -> None:
        assert frame_trace.new_trace_id() != frame_trace.new_trace_id()

    def test_ensure_trace_id_assigns_when_missing(self) -> None:
        item: dict = {"frame": "stub", "camera_id": "camera_0"}
        trace_id = frame_trace.ensure_trace_id(item)
        assert item["trace_id"] == trace_id
        assert len(trace_id) == 32

    def test_ensure_trace_id_idempotent_does_not_overwrite(self) -> None:
        """Промежуточный узел не переназначает trace_id — только источник."""
        item: dict = {"trace_id": "a" * 32}
        trace_id = frame_trace.ensure_trace_id(item)
        assert trace_id == "a" * 32
        assert item["trace_id"] == "a" * 32

    def test_ensure_trace_id_active_without_frame_trace_flag(self, trace_off) -> None:
        """В отличие от stamp_send/record_*, trace_id работает и при выключенном
        INSPECTOR_FRAME_TRACE — нужен в проде для корреляции логов, не только
        для perf-дебага."""
        item: dict = {}
        trace_id = frame_trace.ensure_trace_id(item)
        assert item["trace_id"] == trace_id
        assert trace_id != ""

    def test_ensure_trace_id_non_dict_returns_empty(self) -> None:
        assert frame_trace.ensure_trace_id(None) == ""  # type: ignore[arg-type]

    def test_trace_id_survives_full_chain_alongside_spans(self, trace_on) -> None:
        """trace_id не конфликтует с item["trace"] (span-список) — разные поля,
        оба переживают проброс через несколько узлов (source→detector→painter)."""
        item: dict = {}
        trace_id = frame_trace.ensure_trace_id(item)
        frame_trace.record_process(item, "camera_0", "webcam", 2.0)
        frame_trace.stamp_send(item, "camera_0")
        frame_trace.record_transport(item, "detector")
        # trace_id не тронут спан-механизмом — единственный по кадру.
        assert item["trace_id"] == trace_id
        assert frame_trace.ensure_trace_id(item) == trace_id  # проброс, не пересоздание
        assert len(item["trace"]) == 2
