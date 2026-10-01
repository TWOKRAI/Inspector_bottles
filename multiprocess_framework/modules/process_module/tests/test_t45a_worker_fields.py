# -*- coding: utf-8 -*-
"""Task 4.5a (transport-single-policy) — приёмочные тесты полей воркера кадрового пути.

Два новых поля телеметрии воркера:

* ``pacer_late`` — сколько раз ``FramePacer.wait()`` застал дедлайн уже в прошлом
  (цикл не укладывается в целевой интервал). Отдаётся ``SourceProducer`` и
  ``IdleWorker`` через ``get_cycle_metrics()``.
* ``queue_wait_ms`` — EMA (alpha 0.1, первый отсчёт = сам отсчёт) времени, которое
  пачка провела в ``chain_queue``: ``DataReceiver`` штампует пачку временем
  постановки (``enq_ts``, ``time.perf_counter()``), ``PipelineExecutor`` после
  ``get`` считает ``now - enq_ts``. Отдаётся ``PipelineExecutor.get_cycle_metrics()``.

Оба поля идут в ``build_worker_telemetry`` под гейтом ``allowed_metrics`` и
объявлены в каталоге метрик.

Тесты написаны по контракту задачи, без чтения реализации. Ожидаемые значения —
литералы. Всё, что может зависнуть, гоняется в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    gated_metrics,
)
from multiprocess_framework.modules.process_module.generic.collector_registry import (
    PassThroughCollector,
)
from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver
from multiprocess_framework.modules.process_module.generic.idle_worker import IdleWorker
from multiprocess_framework.modules.process_module.generic.pacing import FramePacer
from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    build_worker_telemetry,
)
from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin

# --------------------------------------------------------------------------- #
# Вспомогательное
# --------------------------------------------------------------------------- #


def _run_in_thread(target, *args) -> threading.Thread:
    """Запустить ``target`` в daemon-потоке (зависание не вешает набор тестов)."""
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


def _stop_and_join(t: threading.Thread, stop: threading.Event, deadline_s: float = 3.0) -> None:
    stop.set()
    t.join(timeout=deadline_s)
    assert not t.is_alive(), "воркер не остановился за дедлайн (зависание)"


def _wait_until(pred, deadline_s: float = 3.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return bool(pred())


class _StampedBatch(list):
    """Пачка «как из DataReceiver»: list с атрибутом ``enq_ts`` (контракт 4.5a)."""


def _stamped(items: list[dict], age_s: float) -> _StampedBatch:
    """Пачка, поставленная в очередь ``age_s`` секунд назад (по perf_counter)."""
    batch = _StampedBatch(items)
    batch.enq_ts = time.perf_counter() - age_s
    return batch


class _SlowSource(ProcessModulePlugin):
    """Источник, чей produce() дольше интервала цикла — цикл всегда опаздывает."""

    name = "slow_cam"
    category = "source"

    def __init__(self, work_s: float) -> None:
        super().__init__()
        self._work_s = work_s
        self._n = 0

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def produce(self) -> list[dict]:
        time.sleep(self._work_s)
        self._n += 1
        return [{"frame": f"f{self._n}", "camera_id": 0, "frame_id": self._n}]


def _make_producer(work_s: float, target_fps: float) -> SourceProducer:
    return SourceProducer(
        plugin=_SlowSource(work_s),
        shm_middleware=None,
        send_fn=lambda t, m: None,
        chain_targets=["out"],
        target_fps=target_fps,
    )


class _BusyIdleWorker(IdleWorker):
    """IdleWorker с нагрузкой ``work_s`` в хуке ``_do_work``."""

    def __init__(self, work_s: float, interval_ms: int) -> None:
        super().__init__(config={"target_interval_ms": interval_ms})
        self._work_s = work_s

    def _do_work(self) -> None:
        time.sleep(self._work_s)


def _make_executor(q: queue.Queue) -> PipelineExecutor:
    ex = PipelineExecutor(
        plugins=[],  # пустая цепочка: items проходят как есть
        chain_targets=["out"],
        shm_middleware=None,
        send_fn=lambda t, m: None,
    )
    ex.bind_queue(q)
    return ex


# --------------------------------------------------------------------------- #
# RED 1. FramePacer.late
# --------------------------------------------------------------------------- #


class TestFramePacerLate:
    """``late`` растёт на каждый wait() с дедлайном в прошлом."""

    def test_t45a_pacer_late_counts_overrun_cycles(self) -> None:
        """Интервал 10 мс, работа 15 мс перед каждым wait → опоздали >= 8 из 10."""
        pacer = FramePacer(0.010)
        stop = threading.Event()
        for _ in range(10):
            time.sleep(0.015)  # «работа» длиннее интервала
            pacer.wait(stop)
        assert pacer.late >= 8

    def test_t45a_pacer_late_stays_zero_without_work(self) -> None:
        """Интервал 10 мс, работы нет → ни одного опоздания (control к тесту выше)."""
        pacer = FramePacer(0.010)
        stop = threading.Event()
        for _ in range(10):
            pacer.wait(stop)
        assert pacer.late == 0
        assert isinstance(pacer.late, int)

    def test_t45a_pacer_first_wait_after_reset_is_not_late(self) -> None:
        """После reset() расписание забыто: следующий wait не считается опозданием,
        даже если «между» прошло 40 мс.  Якорь: до reset опоздание реально засчитано."""
        pacer = FramePacer(0.010)
        stop = threading.Event()
        pacer.wait(stop)  # 1-й wait: не опоздание
        time.sleep(0.030)  # работа длиннее интервала
        pacer.wait(stop)  # 2-й wait: дедлайн в прошлом → +1
        assert pacer.late >= 1, "якорь: опоздание до reset должно быть засчитано"

        pacer.reset()
        late_before = pacer.late
        time.sleep(0.040)  # простой после reset не должен стать опозданием
        pacer.wait(stop)
        assert pacer.late == late_before


# --------------------------------------------------------------------------- #
# RED 2. pacer_late в get_cycle_metrics воркеров-источников
# --------------------------------------------------------------------------- #


class TestPacerLateInWorkerMetrics:
    def test_t45a_source_producer_pacer_late_is_int_zero_before_run(self) -> None:
        producer = _make_producer(work_s=0.0, target_fps=10.0)
        value = producer.get_cycle_metrics()["pacer_late"]
        assert isinstance(value, int) and not isinstance(value, bool)
        assert value == 0

    def test_t45a_source_producer_pacer_late_grows_when_produce_overruns(self) -> None:
        """produce() 40 мс при интервале 20 мс (50 fps) → цикл опаздывает каждый раз."""
        producer = _make_producer(work_s=0.040, target_fps=50.0)
        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(producer.run_loop, stop, pause)
        try:
            assert _wait_until(lambda: producer.get_cycle_metrics()["cycles"] >= 6)
        finally:
            _stop_and_join(t, stop)
        assert producer.get_cycle_metrics()["pacer_late"] >= 3

    def test_t45a_source_producer_pacer_late_zero_when_keeping_up(self) -> None:
        """produce() мгновенный, интервал 100 мс → опозданий нет (control)."""
        producer = _make_producer(work_s=0.0, target_fps=10.0)
        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(producer.run_loop, stop, pause)
        try:
            assert _wait_until(lambda: producer.get_cycle_metrics()["cycles"] >= 3)
        finally:
            _stop_and_join(t, stop)
        assert producer.get_cycle_metrics()["pacer_late"] == 0

    def test_t45a_idle_worker_pacer_late_is_int_zero_before_run(self) -> None:
        worker = IdleWorker(config={"target_interval_ms": 100})
        value = worker.get_cycle_metrics()["pacer_late"]
        assert isinstance(value, int) and not isinstance(value, bool)
        assert value == 0

    def test_t45a_idle_worker_pacer_late_grows_when_work_overruns(self) -> None:
        """_do_work 40 мс при интервале 20 мс → опаздывает каждый цикл."""
        worker = _BusyIdleWorker(work_s=0.040, interval_ms=20)
        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(worker.run, stop, pause)
        try:
            assert _wait_until(lambda: worker.get_cycle_metrics()["cycles"] >= 6)
        finally:
            _stop_and_join(t, stop)
        assert worker.get_cycle_metrics()["pacer_late"] >= 3

    def test_t45a_idle_worker_pacer_late_zero_when_keeping_up(self) -> None:
        """Нагрузки нет, интервал 100 мс → опозданий нет (control)."""
        worker = IdleWorker(config={"target_interval_ms": 100})
        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(worker.run, stop, pause)
        try:
            assert _wait_until(lambda: worker.get_cycle_metrics()["cycles"] >= 3)
        finally:
            _stop_and_join(t, stop)
        assert worker.get_cycle_metrics()["pacer_late"] == 0


# --------------------------------------------------------------------------- #
# RED 3. DataReceiver штампует пачку enq_ts
# --------------------------------------------------------------------------- #


class TestDataReceiverStampsBatch:
    def test_t45a_on_items_ready_puts_list_with_enq_ts(self) -> None:
        chain_q: queue.Queue = queue.Queue(maxsize=10)
        receiver = DataReceiver(
            receive_fn=lambda **kw: None,
            shm_middleware=None,
            item_collector=PassThroughCollector(),
            chain_queue=chain_q,
        )
        items = [{"val": 1}, {"val": 2}, {"val": 3}]

        t0 = time.perf_counter()
        receiver.on_items_ready(items)
        t1 = time.perf_counter()

        got = chain_q.get_nowait()
        # Пачка остаётся списком: те же dict-объекты, тот же порядок.
        assert isinstance(got, list)
        assert got == [{"val": 1}, {"val": 2}, {"val": 3}]
        assert len(got) == 3
        assert got[0] is items[0] and got[1] is items[1] and got[2] is items[2]
        # Штамп = момент постановки по perf_counter.
        assert isinstance(got.enq_ts, float)
        assert t0 <= got.enq_ts <= t1


# --------------------------------------------------------------------------- #
# RED 4. PipelineExecutor.queue_wait_ms
# --------------------------------------------------------------------------- #


class TestPipelineExecutorQueueWait:
    def test_t45a_queue_wait_ms_measures_time_in_queue(self) -> None:
        """Пачка отстояла ~30 мс → queue_wait_ms в [25, 45] (первый отсчёт = сам отсчёт,
        а не 0.1 * 30 = 3)."""
        q: queue.Queue = queue.Queue()
        ex = _make_executor(q)
        q.put(_stamped([{"frame_id": 1}], age_s=0.030))

        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(ex.run, stop, pause)
        try:
            assert _wait_until(lambda: ex.get_cycle_metrics()["cycles"] >= 1)
        finally:
            _stop_and_join(t, stop)
        value = ex.get_cycle_metrics()["queue_wait_ms"]
        assert isinstance(value, float)
        assert 25.0 <= value <= 45.0

    def test_t45a_queue_wait_ms_is_ema_alpha_0_1(self) -> None:
        """Отсчёты ~30 и ~130 мс → EMA = 0.9*30 + 0.1*130 = 40 (допуск на джиттер).
        Не последний отсчёт (130), не alpha 0.5 (80), не alpha 0.2 (50)."""
        q: queue.Queue = queue.Queue()
        ex = _make_executor(q)
        q.put(_stamped([{"frame_id": 1}], age_s=0.030))

        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(ex.run, stop, pause)
        try:
            assert _wait_until(lambda: ex.get_cycle_metrics()["cycles"] >= 1)
            q.put(_stamped([{"frame_id": 2}], age_s=0.130))
            assert _wait_until(lambda: ex.get_cycle_metrics()["cycles"] >= 2)
        finally:
            _stop_and_join(t, stop)
        value = ex.get_cycle_metrics()["queue_wait_ms"]
        assert 38.0 <= value <= 47.0

    def test_t45a_batch_without_enq_ts_is_processed_but_not_counted(self) -> None:
        """Чужая пачка (обычный list без enq_ts): без исключения, обработана,
        queue_wait_ms не меняется. Якорь: перед этим поле уже получило отсчёт ~30 мс."""
        q: queue.Queue = queue.Queue()
        ex = _make_executor(q)
        q.put(_stamped([{"frame_id": 1}], age_s=0.030))

        stop, pause = threading.Event(), threading.Event()
        t = _run_in_thread(ex.run, stop, pause)
        try:
            assert _wait_until(lambda: ex.get_cycle_metrics()["cycles"] >= 1)
            before = ex.get_cycle_metrics()["queue_wait_ms"]
            assert 25.0 <= before <= 45.0, "якорь: первый отсчёт учтён"

            q.put([{"frame_id": 2}])  # обычный list, без enq_ts
            assert _wait_until(lambda: ex.get_cycle_metrics()["cycles"] >= 2)
            time.sleep(0.05)  # запас: если поле «поплывёт», оно успеет
        finally:
            _stop_and_join(t, stop)
        assert ex.get_cycle_metrics()["queue_wait_ms"] == before


# --------------------------------------------------------------------------- #
# RED 5. build_worker_telemetry пробрасывает поля
# --------------------------------------------------------------------------- #


def _workers_snapshot() -> dict:
    return {"w1": {"status": "running", "queue_wait_ms": 12.34, "pacer_late": 3}}


class TestBuildWorkerTelemetryForwardsFields:
    @pytest.mark.parametrize(
        ("allowed", "expect_qw", "expect_pl"),
        [
            (None, True, True),
            ({"queue_wait_ms", "pacer_late"}, True, True),
            ({"queue_wait_ms"}, True, False),
            ({"pacer_late"}, False, True),
        ],
        ids=["no_gate", "both_allowed", "only_queue_wait", "only_pacer_late"],
    )
    def test_t45a_fields_forwarded_when_allowed(self, allowed, expect_qw, expect_pl) -> None:
        result = build_worker_telemetry(_workers_snapshot(), "proc", allowed)
        assert result is not None
        path, data = result
        assert path == "processes.proc"
        w = data["workers"]["w1"]
        assert w["status"] == "running"
        if expect_qw:
            assert w["queue_wait_ms"] == 12.3  # округление до 1 знака
        else:
            assert "queue_wait_ms" not in w
        if expect_pl:
            assert w["pacer_late"] == 3
        else:
            assert "pacer_late" not in w

    def test_t45a_gate_blocks_both_fields(self) -> None:
        """allowed={"fps"} → ни одно из полей не попадает в payload.
        Якорь (иначе тест зелёный вакуумно): без гейта оба поля на месте."""
        _, ungated = build_worker_telemetry(_workers_snapshot(), "proc", None)
        assert ungated["workers"]["w1"]["queue_wait_ms"] == 12.3
        assert ungated["workers"]["w1"]["pacer_late"] == 3

        _, gated = build_worker_telemetry(_workers_snapshot(), "proc", {"fps"})
        w = gated["workers"]["w1"]
        assert "queue_wait_ms" not in w
        assert "pacer_late" not in w
        assert w["status"] == "running"  # status — always-on, вне гейта


# --------------------------------------------------------------------------- #
# RED 6. каталог метрик
# --------------------------------------------------------------------------- #


class TestMetricCatalog:
    def test_t45a_new_metrics_are_declared(self) -> None:
        names = gated_metrics()
        assert "fps" in names, "якорь: каталог фреймворка читается"
        assert "queue_wait_ms" in names
        assert "pacer_late" in names
