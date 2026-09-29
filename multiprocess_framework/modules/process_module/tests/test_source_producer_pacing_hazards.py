"""B-1 (авторский): опасности темпа SourceProducer, которые не видит приёмка по частоте.

Инъекция лида 2026-09-29 (I3): если на ``time.monotonic`` вернуть только ЗАМЕР
(``t_start``/``elapsed``/``record``), а сон оставить точным, приёмка тестера
остаётся зелёной — при мгновенном ``produce()`` ``elapsed`` всё равно ≈ 0, а медиана
квантованной длительности (31.25 мс = 2 тика по 15.6 мс) влезает в её допуск.
Здесь два свойства, которые это ломает:

1. ``produce()`` заметной длительности вычитается из интервала точно — иначе
   ``elapsed`` скачет 0 / 15.6 мс, и кадры идут рывками 27.7 / 43.3 мс. Средняя
   частота при этом держится (квантование несмещено: 0.64·27.7 + 0.36·43.3 ≈ 33.3),
   поэтому сторожим разброс интервала, а не частоту — прежняя версия теста на
   частоту под этим сломом оставалась зелёной (инъекция I3, 2026-09-29).
2. ``cycle_duration_ms`` телеметрии несёт реальную длительность цикла, а не
   ближайшее кратное 15.6 мс.
"""

from __future__ import annotations

import statistics
import threading
import time

from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer


class _SlowPlugin:
    """Source, чей produce() занимает ``work_s`` (точный sleep Python 3.11+)."""

    name = "slow_source"

    def __init__(self, work_s: float) -> None:
        self._work_s = work_s
        self.stamps: list[float] = []

    def produce(self) -> list[dict]:
        self.stamps.append(time.perf_counter())
        time.sleep(self._work_s)
        return []


def _run(work_s: float, window_s: float = 3.0) -> tuple[_SlowPlugin, list[float]]:
    """Крутит run_loop на 30 fps; возвращает плагин и снимки cycle_duration_ms."""
    plugin = _SlowPlugin(work_s)
    producer = SourceProducer(
        plugin=plugin, shm_middleware=None, send_fn=lambda t, m: None, chain_targets=[], target_fps=30.0
    )
    stop, pause = threading.Event(), threading.Event()
    thread = threading.Thread(target=producer.run_loop, args=(stop, pause), daemon=True)
    thread.start()
    time.sleep(1.0)  # разогрев
    durations = []
    deadline = time.perf_counter() + window_s - 1.0
    while time.perf_counter() < deadline:
        durations.append(producer.get_cycle_metrics()["cycle_duration_ms"])
        time.sleep(0.07)
    stop.set()
    thread.join(2.0)
    assert not thread.is_alive(), "run_loop не вышел за 2 с после stop_event"
    return plugin, durations


def test_slow_produce_keeps_frame_intervals_even() -> None:
    plugin, _ = _run(work_s=0.010)
    stamps = plugin.stamps[5:]
    intervals_ms = [(b - a) * 1000.0 for a, b in zip(stamps, stamps[1:])]
    rate = (len(stamps) - 1) / (stamps[-1] - stamps[0])
    jitter = statistics.pstdev(intervals_ms)
    assert 28.5 <= rate <= 31.5, f"produce 10 мс при цели 30 fps дал {rate:.2f}/с"
    # Точный вычет: разброс < 1 мс; квантованный elapsed: ~7.5 мс (рывки 27.7 / 43.3).
    assert jitter < 4.0, (
        f"разброс интервала кадра {jitter:.2f} мс (мин {min(intervals_ms):.1f}, макс {max(intervals_ms):.1f})"
    )


def test_cycle_duration_telemetry_is_not_quantized_to_timer_ticks() -> None:
    _, durations = _run(work_s=0.0)
    median = statistics.median(durations)
    # Реальный цикл 30 fps ≈ 33.4–33.9 мс; квантованный замер даёт 31.25 или 46.9.
    assert 32.3 <= median <= 35.1, f"медиана cycle_duration_ms = {median:.2f} (выборки: {sorted(set(durations))[:6]})"
