# -*- coding: utf-8 -*-
"""CycleMetricsRecorder — общий измеритель тайминга цикла loop-воркеров.

Обобщает паттерн из ``idle_worker.py`` (``_metrics_lock`` / ``_cycle_duration_ms`` /
``_effective_hz`` / ``_cycles`` + ``get_cycle_metrics``) на остальные generic
loop-раннеры (SourceProducer, PipelineExecutor, DataReceiver), чтобы каждый
воркер сам таймировал цикл «начало → конец» и отдавал тайминг в monitoring.

Контракт ключей ОДИН для всех воркеров (важно для агрегации в ProcessMonitor и
для подмешивания в WorkerManager.get_worker_status):
    - cycle_duration_ms: float — длительность последнего цикла, мс («время цикла»)
    - effective_hz: float — частота завершения циклов, усреднённая за последнюю
      секунду (циклов/с); см. record() — НЕ мгновенная 1/cycle
    - target_interval_ms: float — целевой интервал цикла, мс (0 если не задан)
    - cycles: int — число завершённых циклов

Поток: ``record(...)`` зовётся в worker-потоке, ``get_cycle_metrics`` —
из heartbeat-потока. Доступ под ``threading.Lock``.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

# Окно усреднения частоты циклов (циклов/с) — среднее за последнюю секунду.
_HZ_WINDOW_S = 1.0


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
        # Метки завершения циклов (perf_counter) за последнюю секунду —
        # для усреднённой частоты (циклов/с), устойчивой к джиттеру.
        self._completions: deque[float] = deque()

    def record(self, cycle_duration_s: float) -> None:
        """Зафиксировать завершение одного цикла.

        ``effective_hz`` — **средняя частота завершения циклов за последнюю
        секунду** (циклов/с): держим метки завершений в скользящем окне 1 с и
        делим (N-1) на фактический размах окна. Так показатель не дёргается от
        отдельных быстрых/медленных циклов (запрос владельца: «среднее за
        секунду»). НЕ ``1 / cycle_duration``: на Windows ``time.monotonic()``
        имеет гранулярность ~15 мс, а у быстрых consumer-итераций
        (DataReceiver/PipelineExecutor, работа < 1 мс) длительность округлялась
        до 0 → частота 0.

        ``cycle_duration_ms`` — переданная длительность полезной работы итерации
        («время цикла», latency одной обработки), отдельно от частоты.

        Args:
            cycle_duration_s: длительность полезной работы цикла, секунды.
        """
        cycle = max(0.0, float(cycle_duration_s))
        now = time.perf_counter()
        with self._lock:
            self._cycle_duration_ms = cycle * 1000.0
            self._completions.append(now)
            # Выкинуть метки старше окна усреднения.
            cutoff = now - _HZ_WINDOW_S
            while self._completions and self._completions[0] < cutoff:
                self._completions.popleft()
            # Средняя частота = число интервалов / размах окна. При <2 метках
            # (только-только стартовали) частота ещё не определена → 0.
            span = now - self._completions[0]
            n = len(self._completions)
            self._effective_hz = (n - 1) / span if n >= 2 and span > 0 else 0.0
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
        self._t_start = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        # Фиксируем длительность даже при исключении — цикл всё равно прошёл.
        # perf_counter: high-res, корректно меряет subмиллисекундные итерации.
        self._recorder.record(time.perf_counter() - self._t_start)
        return False  # исключения не глушим
