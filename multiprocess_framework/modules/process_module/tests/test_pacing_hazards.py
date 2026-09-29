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
