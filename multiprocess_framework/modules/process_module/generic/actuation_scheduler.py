"""ActuationScheduler — планировщик срабатывания привода (Task 5.2, ADR-PM-051).

Зачем. Решатель (``robot_control``) раньше ждал механизм прямо в ``process()``:
``time.sleep(reject_delay_ms)``. Каждый брак останавливал конвейер процесса на
время транзита изделия до толкателя. Теперь решатель только СТАВИТ цель
``fire_at = capture_ts + transit`` и сразу возвращает item, а исполняет цель этот
планировщик в своём воркере.

Контракт:

* ``schedule(fire_at, window_end, count, payload)`` → ``"scheduled"`` | ``"missed"``.
  ``now > window_end + tolerance`` — окно закрыто: ``missed_items += count``, в кучу
  не ставится. Иначе ``fire_at = max(fire_at, now)`` и постановка.
* ``tick()`` стреляет все ``fire_at <= now``; ``late_fires += 1`` на запись, если
  ``now - fire_at > tolerance``; ``fired_items += count``.
* ``run_loop(stop_event, pause_event)`` — цель воркера (``ExecutionMode.LOOP``).
  На стопе невыстреленное НЕ стреляет: ``unfired_on_stop_items += count``.

``fire(payload, count)`` вызывается ВНЕ ``Condition``: медленный привод не держит
``schedule()`` в потоке исполнителя. Исключение из ``fire`` не убивает цикл: оно
считается (``fire_errors``) и уходит в ``on_error``.
"""

from __future__ import annotations

import heapq
import itertools
import threading
import time
from typing import Any, Callable, Optional

#: Шаг ожидания run_loop: чаще этого цикл проверяет ``stop_event`` и часы.
WAIT_STEP_S = 0.05


class ActuationScheduler:
    """Куча целей привода под ``threading.Condition``.

    Args:
        fire: колбэк ``fire(payload, count)``; зовётся вне замка.
        clock: часы в шкале ``capture_ts`` (``time.time``).
        tolerance_s: допуск по умолчанию для ``missed`` и ``late_fires``.
        on_error: куда отдать исключение ``fire`` (``None`` — только счётчик).
    """

    def __init__(
        self,
        fire: Callable[[Any, int], Any],
        *,
        clock: Callable[[], float] = time.time,
        tolerance_s: float = 0.020,
        on_error: Optional[Callable[[BaseException], Any]] = None,
    ) -> None:
        self._fire = fire
        self._clock = clock
        self._tolerance_s = float(tolerance_s)
        self._on_error = on_error
        self._cond = threading.Condition()
        # Запись кучи: (fire_at, seq, count, payload, tolerance_s). seq ломает
        # равенство fire_at и не даёт сравнивать payload.
        self._heap: list[tuple[float, int, int, Any, float]] = []
        self._seq = itertools.count()
        self._fired_items = 0
        self._missed_items = 0
        self._late_fires = 0
        self._unfired_on_stop_items = 0
        self._fire_errors = 0

    @property
    def tolerance_s(self) -> float:
        return self._tolerance_s

    def schedule(
        self,
        fire_at: float,
        window_end: float,
        count: int,
        payload: Any,
        *,
        tolerance_s: Optional[float] = None,
    ) -> str:
        """Поставить цель. ``tolerance_s=None`` — допуск из конструктора."""
        tol = self._tolerance_s if tolerance_s is None else float(tolerance_s)
        count = int(count)
        with self._cond:
            now = self._clock()
            if now > window_end + tol:
                self._missed_items += count
                return "missed"
            heapq.heappush(self._heap, (max(fire_at, now), next(self._seq), count, payload, tol))
            self._cond.notify()
        return "scheduled"

    def tick(self) -> int:
        """Выстрелить все наступившие цели; вернуть число выстрелов (записей)."""
        due: list[tuple[float, int, int, Any, float]] = []
        with self._cond:
            now = self._clock()
            while self._heap and self._heap[0][0] <= now:
                entry = heapq.heappop(self._heap)
                fire_at, _seq, count, _payload, tol = entry
                if now - fire_at > tol:
                    self._late_fires += 1
                self._fired_items += count
                due.append(entry)
        # Вне замка: медленный fire не держит schedule() исполнителя.
        for _fire_at, _seq, count, payload, _tol in due:
            try:
                self._fire(payload, count)
            except Exception as exc:  # noqa: BLE001 — отказ привода не убивает цикл
                with self._cond:
                    self._fire_errors += 1
                if self._on_error is not None:
                    try:
                        self._on_error(exc)
                    except Exception:  # noqa: BLE001 — сломанный обработчик тоже не убивает
                        pass
        return len(due)

    def pending(self) -> int:
        with self._cond:
            return len(self._heap)

    def stats(self) -> dict:
        """Снимок счётчиков (не живой вид)."""
        with self._cond:
            return {
                "fired_items": self._fired_items,
                "missed_items": self._missed_items,
                "late_fires": self._late_fires,
                "unfired_on_stop_items": self._unfired_on_stop_items,
                "fire_errors": self._fire_errors,
                "pending": len(self._heap),
            }

    def run_loop(self, stop_event: threading.Event, pause_event: threading.Event) -> None:
        """Цель воркера: ждать ближайшую цель, стрелять, на стопе сбросить кучу."""
        while not stop_event.is_set():
            if pause_event.is_set():
                stop_event.wait(WAIT_STEP_S)
                continue
            self.tick()
            with self._cond:
                if stop_event.is_set():
                    break
                if self._heap:
                    delay = self._heap[0][0] - self._clock()
                    if delay > 0:
                        self._cond.wait(min(delay, WAIT_STEP_S))
                else:
                    self._cond.wait(WAIT_STEP_S)
        with self._cond:
            self._unfired_on_stop_items += sum(entry[2] for entry in self._heap)
            self._heap.clear()
