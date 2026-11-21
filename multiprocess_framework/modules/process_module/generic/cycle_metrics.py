# -*- coding: utf-8 -*-
"""CycleMetricsRecorder — общий измеритель тайминга цикла loop-воркеров.

Обобщает паттерн из ``idle_worker.py`` (``_metrics_lock`` / ``_cycle_duration_ms`` /
``_effective_hz`` / ``_cycles`` + ``get_cycle_metrics``) на остальные generic
loop-раннеры (SourceProducer, PipelineExecutor, DataReceiver), чтобы каждый
воркер сам таймировал цикл «начало → конец» и отдавал тайминг в monitoring.

Контракт ключей ОДИН для всех воркеров (важно для агрегации в ProcessMonitor и
для подмешивания в WorkerManager.get_worker_status):
    - cycle_duration_ms: float — длительность последнего цикла, мс («время цикла»)
    - effective_hz: float | None — нижняя оценка темпа на момент ЧТЕНИЯ
      (циклов/с); см. get_cycle_metrics() — НЕ 1/cycle; None, если неизвестна
    - last_cycle_age_s: float | None — возраст последнего завершения, с (None,
      если циклов не было)
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
      perf_counter на входе и фиксирует на выходе).

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
        self._cycles = 0
        # Метки завершения циклов (perf_counter) — для частоты, считаемой В МОМЕНТ
        # ЧТЕНИЯ (см. get_cycle_metrics). Здесь усекаются только ради памяти.
        self._completions: deque[float] = deque()
        # Интервал между двумя последними завершениями, с (0.0 — неизвестен). У
        # ПЕРВОГО завершения — время от создания рекордера: иначе единственный цикл
        # медленной стадии не давал бы никакой оценки темпа. Живёт отдельно от
        # меток: окно в 1 с вытесняет метки, а темп стадии медленнее 1 цикла/с по
        # окну не виден вовсе.
        self._last_interval_s = 0.0
        self._t_created = time.perf_counter()

    def record(self, cycle_duration_s: float) -> None:
        """Зафиксировать завершение одного цикла.

        Только ЗАПОМИНАЕТ: метку завершения и интервал от предыдущей метки (у
        первого завершения — от создания рекордера). Частоту не считает: она
        зависит от момента чтения (возраст последнего завершения растёт, пока
        воркер молчит), и записанная здесь частота оставалась бы прежней вечно.
        Расчёт — :meth:`get_cycle_metrics`.

        ``cycle_duration_ms`` — переданная длительность полезной работы итерации
        («время цикла», latency одной обработки), отдельно от частоты.

        Часы читаются ВНУТРИ лока: метка не может оказаться новее часов читателя,
        который взял лок следом (отрицательный возраст).

        Args:
            cycle_duration_s: длительность полезной работы цикла, секунды.
        """
        cycle = max(0.0, float(cycle_duration_s))
        with self._lock:
            now = time.perf_counter()
            previous = self._completions[-1] if self._completions else self._t_created
            self._last_interval_s = max(0.0, now - previous)
            self._cycle_duration_ms = cycle * 1000.0
            self._completions.append(now)
            # Выкинуть метки старше окна — только память; окно для расчёта
            # отбирается заново от момента чтения.
            cutoff = now - _HZ_WINDOW_S
            while self._completions and self._completions[0] < cutoff:
                self._completions.popleft()
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

        ``effective_hz`` — **мгновенная нижняя оценка темпа на момент чтения** —
        меньшее из известных чисел:

        - средняя частота по меткам окна 1 с, отсчитанного ОТ момента чтения
          (``(n - 1) / размах``, при n >= 2 и размахе > 0), а если в окне метками
          не обойтись — обратный последний интервал ``1 / _last_interval_s``;
        - ``1 / last_cycle_age_s`` — граница сверху: стадия, молчащая дольше
          интервала, не может идти быстрее, чем «один цикл за время молчания»
          (только при возрасте > 0: в момент самого завершения границы нет).

        Следствие: зависшая стадия спадает как 1/возраст, а не залипает на старом
        числе, а стадия медленнее 1 цикла/с даёт её настоящий малый темп, а не 0.
        Ни одно число не известно (две метки в одно мгновение) → ``None``, не 0.
        Циклов не было → 0.0 и ``last_cycle_age_s = None`` (воркер ждёт штатно;
        зависание ДО первого цикла определяется по ``cycles == 0`` и статусу).
        НЕ округляется: при ``round(…, 2)`` стадия медленнее ~1 цикла/200 с
        публиковалась бы как 0.0 — «медленная выглядит мёртвой» вернулась бы в хвосте.

        Это оценка, а не измерение: у нерегулярного потока она шумит, до второго
        завершения грубая (интервал считается от создания рекордера). Истинный
        темп — счётчик ``stage_items_out`` (1.1).

        ``last_cycle_age_s`` — возраст последнего завершения на момент чтения, с
        (``None``, если циклов не было); не округляется.
        """
        with self._lock:
            return self._metrics_locked(time.perf_counter())

    def _metrics_locked(self, now: float) -> dict[str, Any]:
        """Расчёт снимка в момент ``now``. Зовётся ТОЛЬКО под ``self._lock`` (``Lock`` не реентерабелен)."""
        base = {
            "cycle_duration_ms": round(self._cycle_duration_ms, 2),
            "target_interval_ms": round(self._target_interval * 1000.0, 1),
            "cycles": self._cycles,
        }
        if not self._completions:
            return {**base, "effective_hz": 0.0, "last_cycle_age_s": None}

        age = max(0.0, now - self._completions[-1])
        cutoff = now - _HZ_WINDOW_S
        window = [t for t in self._completions if t >= cutoff]
        known: list[float] = []
        span = window[-1] - window[0] if window else 0.0
        if len(window) >= 2 and span > 0:
            known.append((len(window) - 1) / span)
        elif self._last_interval_s > 0:
            known.append(1.0 / self._last_interval_s)
        if age > 0:
            known.append(1.0 / age)
        return {**base, "effective_hz": min(known) if known else None, "last_cycle_age_s": age}


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
