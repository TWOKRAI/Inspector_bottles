# -*- coding: utf-8 -*-
"""Тесты CycleMetricsRecorder и get_cycle_metrics на application-воркерах.

Проверяют, что обобщённый паттерн тайминга цикла (reuse IdleWorker) даёт тот же
контракт ключей на SourceProducer / PipelineExecutor / DataReceiver, и что их
worker target — bound-метод инстанса (иначе WorkerManager.get_worker_status не
подхватит get_cycle_metrics через target.__self__).
"""

import queue
import threading
import time

from multiprocess_framework.modules.process_module.generic.cycle_metrics import (
    CycleMetricsRecorder,
)
from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin


_EXPECTED_KEYS = {"cycle_duration_ms", "effective_hz", "target_interval_ms", "cycles"}


class TestCycleMetricsRecorder:
    def test_contract_keys(self) -> None:
        rec = CycleMetricsRecorder(target_interval_s=0.1)
        snap = rec.get_cycle_metrics()
        assert set(snap.keys()) == _EXPECTED_KEYS

    def test_record_stores_cycle_duration(self) -> None:
        """cycle_duration_ms = переданная длительность работы (latency)."""
        rec = CycleMetricsRecorder()
        rec.record(0.05)  # 50 мс полезной работы
        snap = rec.get_cycle_metrics()
        assert snap["cycle_duration_ms"] == 50.0
        assert snap["cycles"] == 1
        # Один record() — частота ещё не определена (нет предыдущего вызова).
        assert snap["effective_hz"] == 0.0

    def test_effective_hz_from_call_cadence(self) -> None:
        """effective_hz = частота завершения циклов (интервал между record()).

        НЕ 1/cycle_duration: считается по реальному интервалу между record()
        через perf_counter, поэтому корректен и для быстрых consumer-итераций.
        """
        rec = CycleMetricsRecorder()
        rec.record(0.0)
        time.sleep(0.05)  # ~50 мс между завершениями → ~20 Гц
        rec.record(0.0)
        hz = rec.get_cycle_metrics()["effective_hz"]
        # Широкий допуск: планировщик ОС джиттерит, проверяем порядок величины.
        assert 5.0 < hz < 60.0

    def test_effective_hz_is_windowed_average(self) -> None:
        """effective_hz — среднее за окно, а не мгновенное 1/последний-интервал.

        Серия из ~10 циклов с шагом ~10 мс → ~100 Гц. Один аномально долгий
        паузный цикл в конце почти не должен «уронить» усреднённую частоту
        (в отличие от мгновенной 1/interval, которая бы рухнула).
        """
        rec = CycleMetricsRecorder()
        for _ in range(10):
            rec.record(0.0)
            time.sleep(0.01)
        hz_steady = rec.get_cycle_metrics()["effective_hz"]
        assert 40.0 < hz_steady < 200.0  # порядок ~100 Гц, широкий допуск под джиттер ОС

    def test_zero_cycle_no_division_error(self) -> None:
        rec = CycleMetricsRecorder()
        rec.record(0.0)
        snap = rec.get_cycle_metrics()
        assert snap["effective_hz"] == 0.0
        assert snap["cycles"] == 1

    def test_measure_context_manager(self) -> None:
        rec = CycleMetricsRecorder()
        with rec.measure():
            time.sleep(0.02)
        snap = rec.get_cycle_metrics()
        assert snap["cycles"] == 1
        assert snap["cycle_duration_ms"] >= 15.0  # ~20мс с запасом на джиттер

    def test_measure_records_on_exception(self) -> None:
        rec = CycleMetricsRecorder()
        try:
            with rec.measure():
                raise ValueError("boom")
        except ValueError:
            pass
        assert rec.get_cycle_metrics()["cycles"] == 1


# --- Тестовый source-плагин ---


class _FakeSource(ProcessModulePlugin):
    name = "fake_cam"
    category = "source"

    def __init__(self) -> None:
        super().__init__()
        self._n = 0

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def produce(self) -> list[dict]:
        self._n += 1
        return [{"frame": f"f{self._n}", "camera_id": 0, "frame_id": self._n}]


class TestApplicationWorkerCycleMetrics:
    """Application-воркеры отдают effective_hz через get_cycle_metrics."""

    def test_source_producer_reports_hz(self) -> None:
        producer = SourceProducer(
            plugin=_FakeSource(),
            shm_middleware=None,
            send_fn=lambda t, m: None,
            chain_targets=["out"],
            target_fps=50.0,
        )
        assert set(producer.get_cycle_metrics().keys()) == _EXPECTED_KEYS

        stop, pause = threading.Event(), threading.Event()
        t = threading.Thread(target=producer.run_loop, args=(stop, pause))
        t.start()
        time.sleep(0.2)
        stop.set()
        t.join(timeout=1)

        snap = producer.get_cycle_metrics()
        assert snap["cycles"] >= 3
        assert snap["effective_hz"] > 0

    def test_source_producer_run_loop_is_bound_method(self) -> None:
        producer = SourceProducer(
            plugin=_FakeSource(),
            shm_middleware=None,
            send_fn=lambda t, m: None,
            chain_targets=["out"],
        )
        # __self__ резолвится → WorkerManager.get_worker_status подхватит метрики.
        assert getattr(producer.run_loop, "__self__", None) is producer

    def test_pipeline_executor_run_is_bound_method_with_metrics(self) -> None:
        q: queue.Queue = queue.Queue()
        ex = PipelineExecutor(
            plugins=[],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: None,
        )
        ex.bind_queue(q)
        # run — bound-метод инстанса (не lambda), __self__ резолвится.
        assert getattr(ex.run, "__self__", None) is ex
        assert set(ex.get_cycle_metrics().keys()) == _EXPECTED_KEYS

    def test_pipeline_executor_records_on_batch(self) -> None:
        q: queue.Queue = queue.Queue()
        ex = PipelineExecutor(
            plugins=[],  # пустой chain → items проходят как есть
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: None,
        )
        ex.bind_queue(q)
        q.put([{"frame_id": 1}])

        stop, pause = threading.Event(), threading.Event()
        t = threading.Thread(target=ex.run, args=(stop, pause))
        t.start()
        time.sleep(0.15)
        stop.set()
        t.join(timeout=1)

        assert ex.get_cycle_metrics()["cycles"] >= 1

    def test_pipeline_executor_run_without_bind_raises(self) -> None:
        ex = PipelineExecutor(
            plugins=[],
            chain_targets=["out"],
            shm_middleware=None,
            send_fn=lambda t, m: None,
        )
        stop, pause = threading.Event(), threading.Event()
        try:
            ex.run(stop, pause)
            assert False, "ожидался RuntimeError без bind_queue"
        except RuntimeError:
            pass

    def test_data_receiver_run_loop_is_bound_method(self) -> None:
        from unittest.mock import MagicMock

        dr = DataReceiver(
            receive_fn=lambda **kw: None,
            shm_middleware=None,
            inspector_manager=MagicMock(),
            chain_queue=queue.Queue(),
        )
        assert getattr(dr.run_loop, "__self__", None) is dr
        assert set(dr.get_cycle_metrics().keys()) == _EXPECTED_KEYS
