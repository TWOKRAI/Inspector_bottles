# -*- coding: utf-8 -*-
"""Приёмка B-1: источник с target_fps=N отдаёт ~N кадров/с на любой платформе.

Независимые тесты по критериям приёмки (без чтения фикса и чужих тестов).
Субъект — ``SourceProducer.run_loop``. Плагин мгновенный (produce() возвращает
сразу), поэтому темп задаёт только пейсинг цикла. Считаем реальные вызовы
produce() по ``time.perf_counter`` — не по метрикам самого цикла.

Границы — литералы. Не skip на не-Windows: контракт платформонезависим.
Каждый прогон run_loop — в daemon-потоке с join-дедлайном: зависание = FAIL.
"""

from __future__ import annotations

import statistics
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer

#: Окно замера (сек): достаточно длинное, чтобы 1 кадр погоды не делал.
WINDOW_S = 3.0
#: Дедлайн выхода потока после stop_event (сек) — только страховка от зависания.
JOIN_DEADLINE_S = 2.0


class _InstantPlugin:
    """Мгновенный source: фиксирует момент каждого produce() и отдаёт пустую пачку."""

    name = "instant_source"

    def __init__(self) -> None:
        self.stamps: list[float] = []

    def produce(self) -> list[dict]:
        self.stamps.append(time.perf_counter())
        return []


class _Run:
    """run_loop в daemon-потоке + управление остановкой с дедлайном."""

    def __init__(self, target_fps: float) -> None:
        self.plugin = _InstantPlugin()
        self.producer = SourceProducer(
            plugin=self.plugin,
            shm_middleware=None,
            send_fn=lambda target, msg: None,
            chain_targets=[],
            target_fps=target_fps,
        )
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.thread = threading.Thread(target=self.producer.run_loop, args=(self.stop, self.pause), daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop_and_join(self) -> float:
        """Вернуть сек от stop.set() до выхода потока; зависание -> pytest.fail."""
        t0 = time.perf_counter()
        self.stop.set()
        self.thread.join(JOIN_DEADLINE_S)
        if self.thread.is_alive():
            pytest.fail(f"run_loop не вышел за {JOIN_DEADLINE_S}s после stop_event")
        return time.perf_counter() - t0

    def measured_rate(self) -> float:
        """Итераций/с по меткам produce(): (n-1) интервалов / размах меток."""
        stamps = list(self.plugin.stamps)
        assert len(stamps) >= 10, f"цикл почти не крутился: {len(stamps)} вызовов produce()"
        return (len(stamps) - 1) / (stamps[-1] - stamps[0])


def _measure_rate(target_fps: float) -> float:
    run = _Run(target_fps)
    run.start()
    try:
        time.sleep(WINDOW_S)
    finally:
        run.stop_and_join()
    rate = run.measured_rate()
    print(f"[B-1] target_fps={target_fps}: measured {rate:.2f} it/s")
    return rate


def test_30fps_delivers_28_5_to_31_5() -> None:
    rate = _measure_rate(30.0)
    assert 28.5 <= rate <= 31.5, f"target 30 fps, измерено {rate:.2f} it/s"


def test_60fps_delivers_55_to_63() -> None:
    rate = _measure_rate(60.0)
    assert 55.0 <= rate <= 63.0, f"target 60 fps, измерено {rate:.2f} it/s"


def _sample_cycle_metrics_at_30fps() -> list[dict]:
    """Снимки get_cycle_metrics() каждые ~0.1 s на стабильном участке (1..3 s)."""
    run = _Run(30.0)
    run.start()
    snaps: list[dict] = []
    try:
        time.sleep(1.0)  # разогрев: окно effective_hz (1 s) заполнено
        for _ in range(20):
            snaps.append(run.producer.get_cycle_metrics())
            time.sleep(0.1)
    finally:
        run.stop_and_join()
    return snaps


def test_cycle_effective_hz_matches_30fps() -> None:
    snaps = _sample_cycle_metrics_at_30fps()
    hz = statistics.median(s["effective_hz"] for s in snaps)
    print(f"[B-1] metrics effective_hz median {hz:.2f}")
    assert 27.0 <= hz <= 33.0, f"effective_hz медиана {hz:.2f} при target 30 (допуск +-10%)"


def test_cycle_duration_ms_matches_30fps() -> None:
    snaps = _sample_cycle_metrics_at_30fps()
    dur = statistics.median(s["cycle_duration_ms"] for s in snaps)
    print(f"[B-1] metrics cycle_duration_ms median {dur:.2f}")
    assert 30.0 <= dur <= 36.7, f"cycle_duration_ms медиана {dur:.2f} при target 30 (33.3 +-10%)"


def test_stop_returns_within_0_1s() -> None:
    run = _Run(30.0)
    run.start()
    time.sleep(1.0)  # устойчивый ход
    elapsed = run.stop_and_join()
    print(f"[B-1] stop -> exit {elapsed * 1000:.1f} ms")
    assert elapsed < 0.1, f"run_loop вышел за {elapsed:.3f}s после stop_event (лимит 0.1s)"
