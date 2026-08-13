"""LatencyTracker — измерение сквозной задержки обработки.

Без numpy: linear-interpolation percentiles через sorted() (numpy "linear" mode).

Интегрирован с ``BaseManager + ObservableMixin``:
    - ``logger`` → структурное логирование (``self._log_info``)
    - ``stats``  → метрики (``self._record_timing`` для каждого record;
                  периодический snapshot p50/p95/p99 через _record_metric)
"""

from __future__ import annotations

import collections
import math
import time
from typing import Any

from ...base_manager import BaseManager, ObservableMixin


def _quantile_linear(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation квантиль (numpy.quantile method='linear').

    Для q ∈ [0, 1] и отсортированной последовательности длины n возвращает
    sorted[i_lo] + frac * (sorted[i_hi] - sorted[i_lo]), где
    pos = q * (n - 1), i_lo = floor(pos), i_hi = ceil(pos), frac = pos - i_lo.
    """
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    pos = q * (n - 1)
    i_lo = math.floor(pos)
    i_hi = math.ceil(pos)
    if i_lo == i_hi:
        return sorted_vals[i_lo]
    frac = pos - i_lo
    return sorted_vals[i_lo] + frac * (sorted_vals[i_hi] - sorted_vals[i_lo])


class LatencyTracker(BaseManager, ObservableMixin):
    """Трекер сквозной latency (end-to-end).

    Буфер хранит последние buffer_size измерений в миллисекундах.
    Каждые log_interval_sec секунд выводит p50/p95/p99 в лог
    и публикует snapshot в stats manager.

    Args:
        log_interval_sec: Интервал между логами / публикациями snapshot.
        buffer_size: Размер скользящего буфера измерений.
        logger: LoggerManager или ObservableMixin-совместимый объект.
        stats: StatsManager — приёмник метрик (опц.).
        metric_name: Имя метрики в stats (default ``chain.latency``).

    **Единицы: буфер в миллисекундах, метрика в СЕКУНДАХ** (задача 2.2, Р2.2-10).
    Это не описка, а граница двух контрактов. Наружу (``record``, ``percentiles``,
    строка лога) трекер говорит в миллисекундах — так его звали и так читают
    числа глазами. Внутрь, в ``StatsManager.record_timing``, уходят СЕКУНДЫ,
    потому что этот API документирован в секундах, и в них же живут границы
    бакетов (``DEFAULT_DURATION_BUCKETS_SEC``).

    До 2.2 сюда уходили миллисекунды: значение 16.7 (штатный кадр 60 fps) под
    секундными границами улетало в бакет ``+Inf`` целиком, и p95 стал бы
    константой при полностью зелёных тестах. Ловушка была латентной — продовых
    вызывающих у трекера нет, единственные пользователи в дереве это его
    собственные тесты, — поэтому и имя метрики переименовано вместе с единицей:
    суффикс ``_ms`` на значении в секундах был бы той же ложью, только тише.
    """

    def __init__(
        self,
        log_interval_sec: float = 10.0,
        buffer_size: int = 1000,
        logger: Any = None,
        stats: Any = None,
        metric_name: str = "chain.latency",
    ) -> None:
        BaseManager.__init__(self, manager_name="LatencyTracker")
        ObservableMixin.__init__(
            self,
            managers={"logger": logger, "stats": stats},
        )

        self._buffer: collections.deque[float] = collections.deque(maxlen=buffer_size)
        self._log_interval = log_interval_sec
        self._last_log_time = time.time()
        self._metric_name = metric_name

    def initialize(self) -> bool:
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        self._buffer.clear()
        self.is_initialized = False
        return True

    def record(self, e2e_ms: float) -> None:
        """Записать новое измерение latency (миллисекунды) в буфер и в stats.

        В буфер — как пришло (миллисекунды: перцентили и строка лога говорят в
        них). В stats — поделённое на 1000: ``record_timing`` принимает секунды,
        и в секундах же лежат границы бакетов. Пересчёт стоит одного деления и
        стоит на границе, а не размазан по вызывающим.
        """
        self._buffer.append(e2e_ms)
        # Сырое значение в stats (агрегация — забота StatsManager).
        self._record_timing(self._metric_name, e2e_ms / 1000.0)

    def percentiles(self) -> dict[str, float]:
        """Вычислить p50, p95, p99 из накопленного буфера (linear interpolation)."""
        if not self._buffer:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
        sorted_vals = sorted(self._buffer)
        return {
            "p50": _quantile_linear(sorted_vals, 0.50),
            "p95": _quantile_linear(sorted_vals, 0.95),
            "p99": _quantile_linear(sorted_vals, 0.99),
        }

    def maybe_log(self) -> None:
        """Периодически залогировать percentiles + опубликовать snapshot в stats.

        Имена перцентилей сохраняют суффикс ``_ms``, хотя базовое имя метрики
        его потеряло: перцентили публикуются В МИЛЛИСЕКУНДАХ (это значения из
        буфера как есть), и единица обязана стоять в имени там, где она
        отличается от единицы соседа.

        ``time.time()`` здесь оставлен намеренно: интервал 10 с, шаг часов на
        Windows 15.6 мс погоды не делает. Правилу «короткие интервалы — только
        ``perf_counter``» (Р2.2-10) это место не подпадает.

        **Известный дефект, задачей 2.2 НЕ чинится и назван, чтобы не выглядеть
        незамеченным:** перцентили публикуются через ``_record_metric``, а это
        COUNTER — значения СУММИРУЮТСЯ за окно агрегации, и p95=12 мс,
        опубликованный трижды, покажет 36. Нужен ``gauge``. Это дефект типа
        метрики, а не единицы и не часов; правка меняет смысл существующих
        чисел, и делать её попутно в задаче про пределы значило бы прятать
        смену поведения внутри чужого коммита. Продовых вызывающих у трекера
        нет, поэтому цена ожидания — нулевая.
        """
        now = time.time()
        if now - self._last_log_time < self._log_interval:
            return

        p = self.percentiles()
        self._log_info(f"Latency p50={p['p50']:.1f}ms p95={p['p95']:.1f}ms p99={p['p99']:.1f}ms")
        self._record_metric(f"{self._metric_name}_ms.p50", p["p50"])
        self._record_metric(f"{self._metric_name}_ms.p95", p["p95"])
        self._record_metric(f"{self._metric_name}_ms.p99", p["p99"])
        self._last_log_time = now


__all__ = ["LatencyTracker"]
