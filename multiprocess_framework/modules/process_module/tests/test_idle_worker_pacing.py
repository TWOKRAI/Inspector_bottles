"""B-1 (авторский): IdleWorker держит заданный интервал цикла на Windows.

Тот же дефект, что у SourceProducer (приёмка тестера —
``test_source_producer_pacing_acceptance.py``): smart-sleep на ``time.monotonic()``
(GetTickCount64, шаг 15.6 мс на Windows) округлял интервал 33.3 мс до трёх тиков →
~21 цикл/с вместо 30. Меряем частоту вызовов ``_do_work`` по ``perf_counter``,
не имя часов в коде: подмена на любые часы с тем же шагом снова уронит тест.
"""

from __future__ import annotations

import threading
import time

from multiprocess_framework.modules.process_module.generic.idle_worker import IdleWorker


class _CountingWorker(IdleWorker):
    def __init__(self, interval_ms: float) -> None:
        super().__init__(config={"target_interval_ms": interval_ms})
        self.stamps: list[float] = []

    def _do_work(self) -> None:
        self.stamps.append(time.perf_counter())


def _measure_rate(interval_ms: float, window_s: float = 3.0) -> float:
    worker = _CountingWorker(interval_ms)
    stop, pause = threading.Event(), threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop, pause), daemon=True)
    thread.start()
    time.sleep(window_s)
    stop.set()
    thread.join(2.0)
    assert not thread.is_alive(), "воркер не остановился за 2 с после stop_event"
    stamps = worker.stamps[5:]  # разогрев
    return (len(stamps) - 1) / (stamps[-1] - stamps[0])


def test_idle_worker_33ms_interval_runs_near_30_per_second() -> None:
    rate = _measure_rate(33.333)
    assert 28.5 <= rate <= 31.5, f"цикл 33.3 мс дал {rate:.2f}/с (до B-1 на Windows ~21)"


def test_idle_worker_16ms_interval_runs_near_60_per_second() -> None:
    rate = _measure_rate(16.667)
    assert 55.0 <= rate <= 63.0, f"цикл 16.7 мс дал {rate:.2f}/с (до B-1 на Windows ~32)"
