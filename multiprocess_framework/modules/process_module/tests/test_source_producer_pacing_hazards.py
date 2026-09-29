"""B-1 (авторский): опасности темпа SourceProducer и IdleWorker, которые не видит приёмка по частоте.

Инъекция лида 2026-09-29 (I3): если на ``time.monotonic`` вернуть только ЗАМЕР
(``t_start``/``elapsed``/``record``), а сон оставить точным, приёмка тестера
остаётся зелёной — при мгновенном ``produce()`` ``elapsed`` всё равно ≈ 0, а медиана
квантованной длительности (31.25 мс = 2 тика по 15.6 мс) влезает в её допуск.
Здесь свойства, которые это ломает:

1. ``produce()`` заметной длительности вычитается из интервала точно — иначе
   ``elapsed`` скачет 0 / 15.6 мс, и кадры идут рывками 27.7 / 43.3 мс. Средняя
   частота при этом держится (квантование несмещено: 0.64·27.7 + 0.36·43.3 ≈ 33.3),
   поэтому сторожим долю интервалов вне окна, а не частоту.
2. ``cycle_duration_ms`` телеметрии несёт реальную длительность цикла, а не
   ближайшее кратное 15.6 мс — у обоих воркеров (для IdleWorker дыру нашёл ревьюер,
   инъекция J2).

**Часы «как на Windows» (ревью B-1, находка 4).** CI гоняется на Linux, где
``time.monotonic`` точный — откат правки там ничего бы не уронил. Фикстура ``clock``
прогоняет каждый тест дважды: на настоящих часах и на эмуляции Windows, где
``monotonic`` квантован шагом GetTickCount64 (15.625 мс). Это модель ОС, а не шпион
на имени: код, выбравший любые часы с грубым шагом, падает одинаково на обеих ОС.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from types import SimpleNamespace

import pytest

from multiprocess_framework.modules.process_module.generic import idle_worker as idle_worker_mod
from multiprocess_framework.modules.process_module.generic import source_producer as source_producer_mod
from multiprocess_framework.modules.process_module.generic.idle_worker import IdleWorker
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer

#: Шаг GetTickCount64 — гранулярность time.monotonic на Windows (Python 3.12).
_WINDOWS_TICK_S = 0.015625


def _windows_like_time() -> SimpleNamespace:
    """Модуль ``time``, чей monotonic ведёт себя как на Windows; остальное — настоящее."""

    def coarse_monotonic() -> float:
        return math.floor(time.perf_counter() / _WINDOWS_TICK_S) * _WINDOWS_TICK_S

    fake = SimpleNamespace(**{name: getattr(time, name) for name in dir(time) if not name.startswith("__")})
    fake.monotonic = coarse_monotonic
    return fake


@pytest.fixture(params=["real", "windows_like"])
def clock(request, monkeypatch):
    if request.param == "windows_like":
        fake = _windows_like_time()
        monkeypatch.setattr(source_producer_mod, "time", fake)
        monkeypatch.setattr(idle_worker_mod, "time", fake)
    return request.param


class _SlowPlugin:
    """Source, чей produce() занимает ``work_s`` (точный sleep Python 3.11+)."""

    name = "slow_source"

    def __init__(self, work_s: float) -> None:
        self._work_s = work_s
        self.stamps: list[float] = []

    def produce(self) -> list[dict]:
        self.stamps.append(time.perf_counter())
        if self._work_s:
            time.sleep(self._work_s)
        return []


class _CountingIdleWorker(IdleWorker):
    def __init__(self) -> None:
        super().__init__(config={"target_interval_ms": 33.333})
        self.stamps: list[float] = []

    def _do_work(self) -> None:
        self.stamps.append(time.perf_counter())


def _drive(target, metrics, window_s: float = 2.5) -> list[float]:
    """Крутит ``target(stop, pause)`` в daemon-потоке; возвращает снимки cycle_duration_ms."""
    stop, pause = threading.Event(), threading.Event()
    thread = threading.Thread(target=target, args=(stop, pause), daemon=True)
    thread.start()
    time.sleep(0.8)  # разогрев
    durations = []
    deadline = time.perf_counter() + window_s - 0.8
    while time.perf_counter() < deadline:
        durations.append(metrics()["cycle_duration_ms"])
        time.sleep(0.07)
    stop.set()
    thread.join(2.0)
    assert not thread.is_alive(), "цикл не вышел за 2 с после stop_event"
    return durations


def _run_source(work_s: float) -> tuple[_SlowPlugin, list[float]]:
    plugin = _SlowPlugin(work_s)
    producer = SourceProducer(
        plugin=plugin, shm_middleware=None, send_fn=lambda t, m: None, chain_targets=[], target_fps=30.0
    )
    return plugin, _drive(producer.run_loop, producer.get_cycle_metrics)


def _rate(stamps: list[float]) -> float:
    stamps = stamps[5:]
    return (len(stamps) - 1) / (stamps[-1] - stamps[0])


def _assert_duration_not_quantized(durations: list[float]) -> None:
    median = statistics.median(durations)
    # Реальный цикл 30 fps ≈ 33.4–33.9 мс; квантованный замер даёт 31.25 или 46.9.
    assert 32.3 <= median <= 35.1, f"медиана cycle_duration_ms = {median:.2f} (выборки: {sorted(set(durations))[:6]})"


def test_source_rate_holds_30(clock) -> None:
    plugin, _ = _run_source(work_s=0.0)
    rate = _rate(plugin.stamps)
    assert 28.5 <= rate <= 31.5, f"[{clock}] цель 30 fps дала {rate:.2f}/с (грубые часы темпа дают ~21)"


def test_source_slow_produce_keeps_frame_intervals_even(clock) -> None:
    plugin, _ = _run_source(work_s=0.010)
    stamps = plugin.stamps[5:]
    intervals_ms = [(b - a) * 1000.0 for a, b in zip(stamps, stamps[1:])]
    # Доля, а не pstdev (ревью B-1, находка 2): один простой планировщика не должен
    # ронять исправный темп. Точный вычет: почти все интервалы в 33.3 ± 4 мс;
    # квантованный elapsed: рывки 27.7 / 43.3 — вне окна почти все.
    outside = sum(1 for v in intervals_ms if abs(v - 33.333) > 4.0) / len(intervals_ms)
    assert outside < 0.2, (
        f"[{clock}] {outside:.0%} интервалов кадра вне 33.3±4 мс "
        f"(мин {min(intervals_ms):.1f}, макс {max(intervals_ms):.1f})"
    )


def test_source_cycle_duration_telemetry_is_not_quantized(clock) -> None:
    _, durations = _run_source(work_s=0.0)
    _assert_duration_not_quantized(durations)


def test_idle_worker_rate_holds_30(clock) -> None:
    worker = _CountingIdleWorker()
    _drive(worker.run, worker.get_cycle_metrics)
    rate = _rate(worker.stamps)
    assert 28.5 <= rate <= 31.5, f"[{clock}] цикл 33.3 мс дал {rate:.2f}/с (грубые часы темпа дают ~21)"


def test_idle_worker_cycle_duration_telemetry_is_not_quantized(clock) -> None:
    worker = _CountingIdleWorker()
    _assert_duration_not_quantized(_drive(worker.run, worker.get_cycle_metrics))
