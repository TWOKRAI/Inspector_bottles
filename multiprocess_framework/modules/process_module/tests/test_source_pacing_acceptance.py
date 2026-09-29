"""Приёмка pacing цикла источника (Task 4.3a): целевой fps выдерживается точно.

Независимые тесты по критериям A1-A8; реализацию не видели. Всё измеряется
``time.perf_counter`` на стороне теста (``time.monotonic`` на Windows имеет
разрешение 15.6 мс и для измерения не годится). Допуски записаны литералами.

Каждый цикл запускается в daemon-потоке с дедлайном join: зависание превращается
в FAIL, а не в подвисший прогон.
"""

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.idle_worker import IdleWorker
from multiprocess_framework.modules.process_module.generic.source_producer import (
    SourceProducer,
)
from multiprocess_framework.modules.process_module.plugins.base import (
    ProcessModulePlugin,
)

WARMUP_S = 0.3
WINDOW_S = 2.0
JOIN_DEADLINE_S = 2.0


class _TimedSource(ProcessModulePlugin):
    """Источник, чей produce() вызывает произвольный хук (стоимость/блокировка)."""

    name = "pacing_src"
    category = "source"

    def __init__(self, on_produce=None):
        super().__init__()
        self._on_produce = on_produce
        self._n = 0

    def configure(self, ctx): ...
    def start(self, ctx): ...

    def produce(self) -> list[dict]:
        self._n += 1
        if self._on_produce is not None:
            self._on_produce(self._n)
        return [{"frame": self._n, "camera_id": 0, "frame_id": self._n}]


def _busy(seconds: float) -> None:
    """Занять CPU ровно ``seconds`` (sleep на Windows квантуется — не годится)."""
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


def _make_producer(fps: float, on_produce=None):
    stamps: list[float] = []
    producer = SourceProducer(
        plugin=_TimedSource(on_produce),
        shm_middleware=None,
        send_fn=lambda target, msg: stamps.append(time.perf_counter()),
        chain_targets=["out"],  # один получатель: одна отправка = один кадр
        target_fps=fps,
    )
    return producer, stamps


def _start(target, stop_event, pause_event):
    t0 = time.perf_counter()
    thread = threading.Thread(target=target, args=(stop_event, pause_event), daemon=True)
    thread.start()
    return t0, thread


def _sleep_until(deadline: float) -> None:
    while True:
        left = deadline - time.perf_counter()
        if left <= 0:
            return
        time.sleep(min(left, 0.005))


def _stop_and_join(thread, stop_event) -> None:
    stop_event.set()
    thread.join(timeout=JOIN_DEADLINE_S)
    assert not thread.is_alive(), "цикл не завершился за дедлайн после stop_event"


def _count_in(stamps, lo: float, hi: float) -> int:
    return sum(1 for s in list(stamps) if lo <= s < hi)


def _run_source(fps: float, duration_s: float, on_produce=None):
    """Гонит SourceProducer ``duration_s`` секунд, возвращает (t0, stamps)."""
    producer, stamps = _make_producer(fps, on_produce)
    stop, pause = threading.Event(), threading.Event()
    t0, thread = _start(producer.run_loop, stop, pause)
    _sleep_until(t0 + duration_s)
    _stop_and_join(thread, stop)
    return t0, stamps


# --- A1: скорость источника в окне ≥ 2 с после прогрева -----------------------


@pytest.mark.parametrize("fps", [25.0, 50.0, 100.0])
def test_a1_source_rate_within_3_percent_of_target(fps):
    t0, stamps = _run_source(fps, WARMUP_S + WINDOW_S)
    count = _count_in(stamps, t0 + WARMUP_S, t0 + WARMUP_S + WINDOW_S)
    rate = count / WINDOW_S
    assert rate == pytest.approx(fps, rel=0.03), f"target {fps} Hz, got {rate:.2f} Hz ({count} sends / {WINDOW_S}s)"


# --- A2: нет дрейфа -----------------------------------------------------------


def test_a2_no_drift_150_sends_in_3s_at_50fps():
    t0, stamps = _run_source(50.0, 3.0)
    count = _count_in(stamps, t0, t0 + 3.0)
    assert abs(count - 150) <= 3, f"expected 150 +-3 sends in 3.0 s at 50 fps, got {count}"


# --- A3: после долгого produce() кадры не «догоняют» пачкой -------------------


def test_a3_no_catchup_burst_after_long_produce():
    interval = 1 / 50.0
    block_call = 10

    def block_once(n):
        if n == block_call:
            _busy(5 * interval)  # ровно 5 интервалов блокировки

    _, stamps = _run_source(50.0, 1.2, on_produce=block_once)
    stamps = list(stamps)
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    big = max(range(len(gaps)), key=gaps.__getitem__)
    assert gaps[big] >= 4 * interval, "тест сломан: блокировка produce() не отразилась в паузе между отправками"
    after = gaps[big + 1 : big + 4]
    assert len(after) == 3, "после блокировки отправок меньше четырёх"
    # Контракт уточнён лидом после RED-прогона (2026-09-29): ОДИН кадр сразу после
    # задержки допустим — иначе при постоянной перегрузке источник терял бы до половины
    # пропускной способности. Запрещено досылать пропущенные за задержку такты пачкой.
    short = [g for g in after if g < 0.5 * interval]
    assert len(short) <= 1, f"catch-up burst: {len(short)} зазора подряд < {0.5 * interval * 1000:.1f} мс: {after}"
    resumed = stamps[big + 1]
    replayed = _count_in(stamps, resumed, resumed + 5 * interval)
    assert replayed <= 6, f"пропущенные такты досланы пачкой: {replayed} отправок за 5 интервалов после задержки"


# --- A4: стоимость produce() поглощается интервалом ---------------------------


def test_a4_work_time_is_absorbed_by_interval():
    interval = 1 / 50.0

    def cost_40_percent(_n):
        _busy(0.4 * interval)

    t0, stamps = _run_source(50.0, WARMUP_S + WINDOW_S, on_produce=cost_40_percent)
    count = _count_in(stamps, t0 + WARMUP_S, t0 + WARMUP_S + WINDOW_S)
    assert count / WINDOW_S == pytest.approx(50.0, rel=0.03), f"got {count / WINDOW_S:.2f} Hz"


# --- A5: отзывчивость на stop -------------------------------------------------


def test_a5_stop_mid_wait_returns_within_100ms_at_1fps():
    producer, stamps = _make_producer(1.0)
    stop, pause = threading.Event(), threading.Event()
    finished: list[float] = []

    def target(s, p):
        producer.run_loop(s, p)
        finished.append(time.perf_counter())

    _, thread = _start(target, stop, pause)
    time.sleep(0.4)  # первый кадр ушёл, цикл ждёт следующий (~1 с)
    t_stop = time.perf_counter()
    stop.set()
    thread.join(timeout=JOIN_DEADLINE_S)
    assert not thread.is_alive(), "run_loop не вернулся после stop_event"
    assert finished[0] - t_stop <= 0.100, f"stop -> return {(finished[0] - t_stop) * 1000:.0f} мс > 100 мс"


# --- A6: телеметрия честная ---------------------------------------------------


def test_a6_effective_hz_within_5_percent_of_100():
    producer, _ = _make_producer(100.0)
    stop, pause = threading.Event(), threading.Event()
    t0, thread = _start(producer.run_loop, stop, pause)
    _sleep_until(t0 + WARMUP_S + WINDOW_S + 0.2)
    metrics = producer.get_cycle_metrics()
    _stop_and_join(thread, stop)
    assert metrics["effective_hz"] == pytest.approx(100.0, rel=0.05), metrics


# --- A7: IdleWorker -----------------------------------------------------------


class _StampedIdle(IdleWorker):
    def __init__(self, interval_ms: int):
        super().__init__(process=None, config={"target_interval_ms": interval_ms})
        self.stamps: list[float] = []

    def _do_work(self, *args, **kwargs):
        self.stamps.append(time.perf_counter())


@pytest.mark.parametrize("interval_ms, hz", [(10, 100.0), (20, 50.0)])
def test_a7_idle_worker_cycle_rate_within_3_percent(interval_ms, hz):
    worker = _StampedIdle(interval_ms)
    stop, pause = threading.Event(), threading.Event()
    t0, thread = _start(worker.run, stop, pause)
    _sleep_until(t0 + WARMUP_S + WINDOW_S)
    _stop_and_join(thread, stop)
    count = _count_in(worker.stamps, t0 + WARMUP_S, t0 + WARMUP_S + WINDOW_S)
    assert count / WINDOW_S == pytest.approx(hz, rel=0.03), f"target {hz} Hz, got {count / WINDOW_S:.2f} Hz"


# --- A8: пауза ----------------------------------------------------------------


def _pause_resume(producer, stamps, paused_s: float, after_s: float):
    """0.5 с работы -> пауза paused_s -> снятие паузы, ещё after_s. Возвращает (n_paused_delta, resume_at)."""
    stop, pause = threading.Event(), threading.Event()
    t0, thread = _start(producer.run_loop, stop, pause)
    _sleep_until(t0 + 0.5)
    pause.set()
    time.sleep(0.06)  # дать завершиться уже начатому циклу (3 интервала)
    n_paused = len(stamps)
    time.sleep(paused_s)
    sent_while_paused = len(stamps) - n_paused
    resume_at = time.perf_counter()
    pause.clear()
    _sleep_until(resume_at + after_s)
    _stop_and_join(thread, stop)
    return sent_while_paused, resume_at


def test_a8_pause_silences_sends_and_resume_has_no_burst():
    interval = 1 / 50.0
    producer, stamps = _make_producer(50.0)
    sent_while_paused, resume_at = _pause_resume(producer, stamps, paused_s=0.4, after_s=0.5)
    assert sent_while_paused == 0, f"на паузе отправлено {sent_while_paused} кадров"
    after = [s for s in list(stamps) if s >= resume_at]
    gaps = [b - a for a, b in zip(after, after[1:])]
    assert len(gaps) >= 4, "после снятия паузы почти нет отправок"
    for g in gaps[:3]:
        assert g >= 0.5 * interval, f"burst после паузы: зазор {g * 1000:.1f} мс"


def test_a8_rate_returns_to_target_after_pause():
    producer, stamps = _make_producer(50.0)
    _, resume_at = _pause_resume(producer, stamps, paused_s=0.2, after_s=WARMUP_S + WINDOW_S)
    count = _count_in(stamps, resume_at + WARMUP_S, resume_at + WARMUP_S + WINDOW_S)
    assert count / WINDOW_S == pytest.approx(50.0, rel=0.03), f"после паузы {count / WINDOW_S:.2f} Гц"
