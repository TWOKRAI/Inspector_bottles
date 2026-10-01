"""Task 4.3a — авторские тесты опасных мест ``FramePacer`` (дополняют приёмку
``test_source_pacing_acceptance.py``, не заменяют её).

Опасность, видная только изнутри: расписание переживает паузу. Без ``reset()``
первый такт после паузы видит «опоздание» на всю паузу и следующий кадр уходит
сразу — два цикла подряд без интервала. У ``SourceProducer`` это ловит приёмка
A8a; у ``IdleWorker`` — только этот файл.
"""

import threading
import time

from multiprocess_framework.modules.process_module.generic.idle_worker import IdleWorker
from multiprocess_framework.modules.process_module.generic.pacing import FramePacer

JOIN_DEADLINE_S = 2.0


class _StampedIdle(IdleWorker):
    def __init__(self, stamps: list[float], interval_ms: int) -> None:
        super().__init__(config={"target_interval_ms": interval_ms})
        self._stamps = stamps

    def _do_work(self) -> None:
        self._stamps.append(time.perf_counter())


def test_idle_worker_resume_after_pause_has_no_back_to_back_cycles():
    """Красит: убрать ``self._pacer.reset()`` из ветки паузы ``IdleWorker.run``."""
    interval = 0.02
    stamps: list[float] = []
    worker = _StampedIdle(stamps, 20)
    stop, pause = threading.Event(), threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop, pause), daemon=True)
    thread.start()
    try:
        time.sleep(0.2)
        pause.set()
        time.sleep(0.3)
        resumed_at = time.perf_counter()
        pause.clear()
        time.sleep(0.2)
    finally:
        stop.set()
        thread.join(JOIN_DEADLINE_S)
    assert not thread.is_alive(), "IdleWorker не остановился за дедлайн"
    after = [s for s in stamps if s >= resumed_at]
    assert len(after) >= 4, f"после паузы циклов мало: {len(after)}"
    gaps = [b - a for a, b in zip(after, after[1:4])]
    assert all(g >= 0.5 * interval for g in gaps), f"циклы подряд после паузы: {[round(g * 1000, 1) for g in gaps]} мс"


def test_pacer_stop_event_interrupts_long_wait():
    """Красит: сон одним куском (``time.sleep(left)``) вместо порций — stop ждал бы секунду."""
    pacer = FramePacer(1.0)
    stop = threading.Event()
    threading.Timer(0.05, stop.set).start()
    t0 = time.perf_counter()
    pacer.wait(stop)
    assert time.perf_counter() - t0 < 0.15, "wait не отреагировал на stop_event"


# --- ревью 4.3a: три свойства, которые не держал ни один тест ------------------------


def _busy(seconds: float) -> None:
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


def test_sustained_overload_period_is_work_time_not_work_plus_interval():
    """Цель 50 fps, produce() стоит 30 мс: период = время работы (33.3 Гц), а не работа +
    интервал (20 Гц). Красит: при опоздании ``nxt = now + interval`` — ради этого ослаблен A3."""
    from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer
    from multiprocess_framework.modules.process_module.plugins.base import ProcessModulePlugin

    class _Slow(ProcessModulePlugin):
        name = "slow_src"
        category = "source"

        def configure(self, ctx): ...
        def start(self, ctx): ...

        def produce(self) -> list[dict]:
            _busy(0.030)
            return [{"frame": 1}]

    stamps: list[float] = []
    producer = SourceProducer(
        plugin=_Slow(),
        shm_middleware=None,
        send_fn=lambda t, m: stamps.append(time.perf_counter()),
        chain_targets=["out"],
        target_fps=50.0,
    )
    stop, pause = threading.Event(), threading.Event()
    thread = threading.Thread(target=producer.run_loop, args=(stop, pause), daemon=True)
    t0 = time.perf_counter()
    thread.start()
    time.sleep(2.3)
    stop.set()
    thread.join(JOIN_DEADLINE_S)
    assert not thread.is_alive()
    rate = sum(1 for s in stamps if t0 + 0.3 <= s < t0 + 2.3) / 2.0
    assert 31.5 <= rate <= 35.0, f"под перегрузкой {rate:.1f} Гц, ожидалось ~33.3 (20 = регрессия work+interval)"


def test_pacer_sleeps_not_spins():
    """0.5 с на 100 Гц: CPU потока < 0.1 с. Наблюдаемый эффект, а не шпион на ``time.sleep``:
    тиковый учёт Windows может недоучесть спящий поток, но спин не спрячет.
    Красит: досыпание спином (``time.sleep`` → no-op) — 0.5 с CPU за 0.5 с."""
    pacer, stop = FramePacer(0.01), threading.Event()
    c0, t0 = time.thread_time(), time.perf_counter()
    while time.perf_counter() - t0 < 0.5:
        pacer.wait(stop)
    assert time.thread_time() - c0 < 0.1


def test_idle_cycle_duration_measured_with_fine_clock():
    """``cycle_duration_ms`` при интервале 10 мс лежит в 10 ± 2. Красит: длительность цикла
    на ``time.monotonic`` (Windows: 0 / 15 / 16 мс)."""
    worker = _StampedIdle([], 10)
    stop, pause = threading.Event(), threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop, pause), daemon=True)
    thread.start()
    samples = []
    for _ in range(20):
        time.sleep(0.025)
        samples.append(worker.get_cycle_metrics()["cycle_duration_ms"])
    stop.set()
    thread.join(JOIN_DEADLINE_S)
    assert not thread.is_alive()
    assert all(8.0 <= s <= 12.0 for s in samples[2:]), f"cycle_duration_ms вне 10±2: {samples}"
