# -*- coding: utf-8 -*-
"""CycleMetricsRecorder — общий измеритель тайминга цикла loop-воркеров.

Обобщает паттерн из ``idle_worker.py`` (``_metrics_lock`` / ``_cycle_duration_ms`` /
``_effective_hz`` / ``_cycles`` + ``get_cycle_metrics``) на остальные generic
loop-раннеры (SourceProducer, PipelineExecutor, DataReceiver), чтобы каждый
воркер сам таймировал цикл «начало → конец» и отдавал тайминг в monitoring.

Контракт ключей ОДИН для всех воркеров (важно для агрегации в ProcessMonitor и
для подмешивания в WorkerManager.get_worker_status):
    - cycle_duration_ms: float — длительность последнего цикла, мс
    - effective_hz: float — фактическая частота = 1 / длительность цикла
    - target_interval_ms: float — целевой интервал цикла, мс (0 если не задан)
    - cycles: int — число завершённых циклов

Поток: ``record(...)`` зовётся в worker-потоке, ``get_cycle_metrics`` —
из heartbeat-потока. Доступ под ``threading.Lock``.
"""

from __future__ import annotations

import threading
import time
from typing import Any


class CycleMetricsRecorder:
    """Потокобезопасный аккумулятор тайминга цикла.

    Воркер держит экземпляр (``self._cycle_metrics``) и вызывает один из:

    - ``record(cycle_duration_s)`` — если сам замерил длительность цикла;
    - контекст-менеджер ``measure()`` — обернуть тело итерации (засекает
      monotonic на входе и фиксирует на выходе).

    ``get_cycle_metrics`` отдаёт снимок в том же формате, что IdleWorker.
    """

    def __init__(self, target_interval_s: float = 0.0) -> None:
        """
        Args:
            target_interval_s: целевой интервал цикла в секундах (для
                ``target_interval_ms`` в снимке). 0 — если воркер без явного
                throttle (например DataReceiver на блокирующем receive).
        """
        self._target_interval = max(0.0, float(target_interval_s))
        self._lock = threading.Lock()
        self._cycle_duration_ms = 0.0
        self._effective_hz = 0.0
        self._cycles = 0

    def record(self, cycle_duration_s: float) -> None:
        """Зафиксировать длительность одного завершённого цикла (секунды)."""
        cycle = max(0.0, float(cycle_duration_s))
        with self._lock:
            self._cycle_duration_ms = cycle * 1000.0
            self._effective_hz = (1.0 / cycle) if cycle > 0 else 0.0
            self._cycles += 1

    def measure(self) -> "_CycleMeasurement":
        """Контекст-менеджер: ``with self._cycle_metrics.measure(): ...``.

        Засекает время на входе, на выходе вычисляет длительность и зовёт
        ``record``. Удобно оборачивать тело итерации loop.
        """
        return _CycleMeasurement(self)

    def get_cycle_metrics(self) -> dict[str, Any]:
        """Снимок тайминга цикла (потокобезопасно).

        WorkerManager.get_worker_status подмешивает результат в статус воркера →
        heartbeat → ProcessMonitor → GUI.
        """
        with self._lock:
            return {
                "cycle_duration_ms": round(self._cycle_duration_ms, 2),
                "effective_hz": round(self._effective_hz, 2),
                "target_interval_ms": round(self._target_interval * 1000.0, 1),
                "cycles": self._cycles,
            }


class _CycleMeasurement:
    """Внутренний контекст-менеджер для CycleMetricsRecorder.measure()."""

    __slots__ = ("_recorder", "_t_start")

    def __init__(self, recorder: CycleMetricsRecorder) -> None:
        self._recorder = recorder
        self._t_start = 0.0

    def __enter__(self) -> "_CycleMeasurement":
        self._t_start = time.monotonic()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        # Фиксируем длительность даже при исключении — цикл всё равно прошёл.
        self._recorder.record(time.monotonic() - self._t_start)
        return False  # исключения не глушим
