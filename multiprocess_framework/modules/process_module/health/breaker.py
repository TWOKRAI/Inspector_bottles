# -*- coding: utf-8 -*-
"""CircuitBreaker — честный circuit breaker поверх счётчика подряд-ошибок (Ф2 Task 2.2).

Зачем отдельный примитив
------------------------
Существовавший breaker в ``PipelineExecutor`` «нечестный»: он видел только те
исключения, что всплывали из ``plugin.process()``. Ошибки, проглоченные внутри
плагина (``try/except: pass``), в счётчик не попадали — отказ соседа/железа
оставался невидимым. Ф2 ввела честный канал наблюдаемости ``ctx.health.report_error``
(инкрементит на КАЖДУЮ проглоченную ошибку). Этот breaker вешается на тот же
счётчик: N подряд ``report_error`` без успеха между ними → breaker OPEN →
процесс переходит в ``degraded``.

Модель состояний (кооперативная, без внешнего таймера)
------------------------------------------------------
- ``CLOSED``  — норма. ``record_failure`` копит подряд-счётчик; достиг порога
  ``fail_threshold`` → ``OPEN``.
- ``OPEN``    — сработал. Полёт ``poll()`` после ``cooldown_sec`` тишины (нет новых
  ошибок) → ``HALF_OPEN`` (проба). Явный ``record_success`` → сразу ``CLOSED``.
- ``HALF_OPEN`` — пробный период. ``record_success`` → ``CLOSED`` (восстановились);
  ``record_failure`` → снова ``OPEN`` (проба провалилась); ещё ``cooldown_sec``
  тишины на ``poll()`` → ``CLOSED`` (шторм утих сам).

Таким образом восстановление возможно ДВУМЯ путями: явный успех (``record_success``
из loop-раннера, у которого есть сигнал «итерация удалась») ИЛИ пассивно —
через тишину и ``poll()`` для сайтов, которые умеют только ``report_error``.

Подряд-счётчик (``consecutive``) — ОТДЕЛЬНЫЙ от кумулятивного ``HealthState.errors``
(тот монотонный, не сбрасывается): breaker меряет «плохо ПРЯМО СЕЙЧАС», а errors —
«сколько всего с старта».

Thread-safety: мутации под ``_lock`` (breaker дёргают из worker-потоков); чтение
``state`` — lock-free (атомарное чтение строкового атрибута в CPython), чтобы
snapshot HealthState не вкладывал блокировки.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

#: Порог по умолчанию: столько подряд-ошибок открывают breaker.
DEFAULT_FAIL_THRESHOLD = 5

#: Окно тишины по умолчанию (сек): столько без новых ошибок → шаг восстановления.
DEFAULT_COOLDOWN_SEC = 30.0


class BreakerState:
    """Состояния breaker (значение уходит в state-дерево как ``health.breaker``)."""

    CLOSED = "closed"  # норма
    OPEN = "open"  # сработал — деградация
    HALF_OPEN = "half_open"  # пробный период восстановления


class CircuitBreaker:
    """Честный circuit breaker на подряд-счётчике отказов.

    Методы-мутаторы возвращают строку нового состояния ТОЛЬКО при смене состояния
    (иначе ``None``) — вызывающая сторона по ней решает, дёргать ли health-колбэк
    (``OPEN`` → degraded, ``CLOSED`` → ok). Промежуточный ``HALF_OPEN`` тоже
    возвращается (нужно опубликовать признак в дерево), но health-статус не меняет.

    Args:
        fail_threshold: сколько подряд-ошибок открывают breaker (>=1).
        cooldown_sec: окно тишины для шага восстановления.
        clock: источник времени (инъекция для детерминизма в тестах).
    """

    def __init__(
        self,
        *,
        fail_threshold: int = DEFAULT_FAIL_THRESHOLD,
        cooldown_sec: float = DEFAULT_COOLDOWN_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = max(1, int(fail_threshold))
        self._cooldown = max(0.0, float(cooldown_sec))
        self._clock = clock
        self._lock = threading.Lock()

        self._state = BreakerState.CLOSED
        self._consecutive = 0
        self._last_fail_ts = 0.0

    # --- чтение (lock-free: атомарное чтение атрибутов) ---

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_open(self) -> bool:
        # OPEN и HALF_OPEN оба означают «breaker ещё не восстановлен» — для
        # решения о backoff в loop-раннере это одно и то же.
        return self._state != BreakerState.CLOSED

    @property
    def consecutive(self) -> int:
        return self._consecutive

    @property
    def threshold(self) -> int:
        return self._threshold

    @property
    def cooldown_sec(self) -> float:
        return self._cooldown

    # --- мутации ---

    def record_failure(self) -> str | None:
        """Учесть один отказ. Вернуть новое состояние при переходе, иначе None."""
        with self._lock:
            self._consecutive += 1
            self._last_fail_ts = self._clock()

            if self._state == BreakerState.CLOSED:
                if self._consecutive >= self._threshold:
                    self._state = BreakerState.OPEN
                    return BreakerState.OPEN
                return None

            if self._state == BreakerState.HALF_OPEN:
                # Проба провалилась — снова открываемся.
                self._state = BreakerState.OPEN
                return BreakerState.OPEN

            # Уже OPEN — просто копим (для видимости consecutive), без перехода.
            return None

    def record_success(self) -> str | None:
        """Учесть успех. Сбрасывает подряд-счётчик; закрывает breaker при переходе."""
        with self._lock:
            self._consecutive = 0
            if self._state != BreakerState.CLOSED:
                self._state = BreakerState.CLOSED
                return BreakerState.CLOSED
            return None

    def poll(self) -> str | None:
        """Пассивный шаг восстановления по тишине. Вернуть новое состояние или None.

        Зовётся периодически (в heartbeat такте / loop-итерации). Для сайтов,
        которые умеют только ``report_error`` и не шлют ``record_success``, это
        единственный путь назад к ``CLOSED``: OPEN → (тишина) → HALF_OPEN →
        (ещё тишина) → CLOSED.
        """
        with self._lock:
            if self._state == BreakerState.CLOSED:
                return None
            quiet = self._clock() - self._last_fail_ts
            if quiet < self._cooldown:
                return None
            if self._state == BreakerState.OPEN:
                self._state = BreakerState.HALF_OPEN
                # Сдвигаем точку отсчёта, чтобы до CLOSED нужна была ещё тишина.
                self._last_fail_ts = self._clock()
                return BreakerState.HALF_OPEN
            # HALF_OPEN + тишина ещё на cooldown → окончательно закрываемся.
            self._state = BreakerState.CLOSED
            self._consecutive = 0
            return BreakerState.CLOSED

    def snapshot(self) -> dict:
        """Диагностический снимок (для health.status / отладки)."""
        with self._lock:
            return {
                "state": self._state,
                "consecutive": self._consecutive,
                "threshold": self._threshold,
                "cooldown_sec": self._cooldown,
            }
