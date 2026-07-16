# -*- coding: utf-8 -*-
"""perf_probes — лёгкие замеры latency этапов кадра (HP-1, Ф7 G.1).

Идея: заменить снятые TRACE-логи (человеко-читаемый спам каждый N-й кадр) на
структурные p50/p99-замеры по этапам кадра (capture → send → receive →
restore), доступные через штатный stats-механизм воркера — те же
``get_cycle_metrics()``, что уже несут ``cycle_duration_ms``/``effective_hz``
в heartbeat → ``ProcessMonitor`` → GUI (см. ``cycle_metrics.py``). Никаких
print и никакого нового IPC-канала — просто дополнительный ключ в уже
существующем снимке.

Гейтится ``FW_PERF_PROBES=1`` (читается один раз при импорте, дочерние spawn-
процессы наследуют env — та же конвенция, что у ``frame_trace.INSPECTOR_
FRAME_TRACE``). Дефолт OFF: ``measure()`` возвращает общий no-op контекст-
менеджер — НИ ОДНОГО вызова ``time.perf_counter()`` на кадр, только один
bool-чек. Тесты могут переопределить: ``perf_probes._ENABLED = True``.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from ...config_module.feature_flags import is_enabled

_ENABLED = is_enabled("FW_PERF_PROBES")

#: Сколько последних замеров держим на этап — компромисс память/точность p99.
_WINDOW = 200


def enabled() -> bool:
    """Включены ли perf-пробы (по env ``FW_PERF_PROBES``)."""
    return _ENABLED


class LatencyProbes:
    """Per-stage латентность кадра (capture/send/receive/restore).

    Один инстанс на воркер (``SourceProducer``/``DataReceiver``). При
    выключенном флаге ``measure()`` не аллоцирует и не мерит время — общий
    ``_NOOP_MEASUREMENT``-синглтон на всех.
    """

    def __init__(self) -> None:
        self._samples: dict[str, deque[float]] = {}

    def measure(self, stage: str) -> "_ProbeMeasurement | _NoopMeasurement":
        """Контекст-менеджер вокруг одного замера этапа ``stage``.

        При ``_ENABLED=False`` — ноль вызовов ``time.perf_counter()`` (общий
        no-op синглтон, не завязан на конкретный ``stage``).
        """
        if not _ENABLED:
            return _NOOP_MEASUREMENT
        return _ProbeMeasurement(self, stage)

    def _record(self, stage: str, ms: float) -> None:
        bucket = self._samples.get(stage)
        if bucket is None:
            bucket = deque(maxlen=_WINDOW)
            self._samples[stage] = bucket
        bucket.append(ms)

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Снимок p50/p99/count по каждому этапу (для get_cycle_metrics()).

        Вызывается ТОЛЬКО когда флаг включён (см. вызывающих в source_producer/
        data_receiver) — при off словарь пуст (замеров нет), лишний вызов сам
        по себе безвреден (пустой dict), но не нужен.
        """
        out: dict[str, dict[str, Any]] = {}
        for stage, samples in self._samples.items():
            if not samples:
                continue
            ordered = sorted(samples)
            out[stage] = {
                "p50_ms": _percentile(ordered, 0.50),
                "p99_ms": _percentile(ordered, 0.99),
                "count": len(ordered),
            }
        return out


def _percentile(ordered: list[float], q: float) -> float:
    """Ближайший-ранг перцентиль по уже отсортированному списку."""
    if not ordered:
        return 0.0
    idx = min(len(ordered) - 1, int(len(ordered) * q))
    return round(ordered[idx], 3)


class _ProbeMeasurement:
    """Активный замер: ``with probes.measure("capture"): ...``."""

    __slots__ = ("_probes", "_stage", "_t0")

    def __init__(self, probes: LatencyProbes, stage: str) -> None:
        self._probes = probes
        self._stage = stage
        self._t0 = 0.0

    def __enter__(self) -> "_ProbeMeasurement":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        # Фиксируем время даже при исключении — этап всё равно занял время.
        self._probes._record(self._stage, (time.perf_counter() - self._t0) * 1000.0)
        return False  # исключения не глушим


class _NoopMeasurement:
    """Общий no-op контекст-менеджер (флаг off) — ноль вызовов perf_counter."""

    __slots__ = ()

    def __enter__(self) -> "_NoopMeasurement":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


_NOOP_MEASUREMENT = _NoopMeasurement()
