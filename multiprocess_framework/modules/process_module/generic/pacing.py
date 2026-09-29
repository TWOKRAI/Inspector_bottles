"""FramePacer — темп цикла по абсолютному расписанию (Task 4.3a, transport-single-policy).

Раньше циклы (``SourceProducer``, ``IdleWorker``) спали «интервал минус время работы»
по ``time.monotonic()``. На Windows у ``monotonic`` шаг 15.625 мс (GetTickCount64),
поэтому ожидание кончалось только на следующем тике: цель 25 fps давала ~21.7 Гц,
50 → 32, 100 → 64 (замер 2026-09-29, `docs/audits/2026-09-29_high-fps-perf-review.md`).

Здесь:
- часы ``time.perf_counter()`` — монотонные на всех ОС, разрешение ~100 нс, без
  веток под платформу;
- дедлайн следующего такта = предыдущий дедлайн + интервал: время работы
  поглощается, ошибка сна не накапливается (нет дрейфа);
- опоздали (работа длиннее интервала или задержка) → расписание от «сейчас»:
  следующий цикл стартует сразу, пропущенные такты НЕ досылаются пачкой;
- сон — ``time.sleep`` порциями ≤ 10 мс: ``Event.wait``/``Queue.get`` с таймаутом
  на Windows квантуются теми же 15.6 мс, а порции держат отзывчивость на stop.
"""

from __future__ import annotations

import threading
import time

#: Порция сна: отзывчивость на stop_event не хуже этого значения.
_SLEEP_CHUNK_S = 0.01


class FramePacer:
    """Держит цикл на целевом интервале. Не потокобезопасен: один поток-владелец.

    Использование: после полезной работы итерации — ``wait(stop_event)``; после
    паузы/простоя, когда расписание потеряло смысл, — ``reset()``.
    """

    def __init__(self, interval_s: float) -> None:
        self._interval = max(0.0, float(interval_s))
        self._next: float | None = None

    def reset(self) -> None:
        """Забыть расписание: следующий ``wait`` отсчитает интервал от «сейчас»."""
        self._next = None

    def wait(self, stop_event: threading.Event) -> None:
        """Спать до дедлайна следующего такта (или до stop_event)."""
        now = time.perf_counter()
        nxt = (now if self._next is None else self._next) + self._interval
        if nxt < now:
            # Опоздали: такты, пропущенные за время работы, не досылаем пачкой.
            nxt = now
        self._next = nxt
        while not stop_event.is_set():
            left = nxt - time.perf_counter()
            if left <= 0:
                return
            time.sleep(min(_SLEEP_CHUNK_S, left))
