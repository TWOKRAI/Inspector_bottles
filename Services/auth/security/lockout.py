# -*- coding: utf-8 -*-
"""
LockoutTracker — in-memory трекер блокировок при неудачных входах.

Хранит для каждого пользователя: число неудач и timestamp следующего
разрешённого входа. При успешном входе или по истечении reset_after_sec
счётчик сбрасывается.

Thread-safe через threading.Lock.

Состояние in-memory: перезапуск приложения сбрасывает счётчики.
Это сделано намеренно (Auth-004, см. DECISIONS.md).

Использование:
    from Services.auth.policies import LockoutPolicy
    from Services.auth.lockout_tracker import LockoutTracker

    tracker = LockoutTracker(LockoutPolicy())

    tracker.record_failure("alice")
    locked, wait_sec = tracker.is_locked("alice")
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from ..crypto.policies import LockoutPolicy


@dataclass
class _AccountState:
    """Внутреннее состояние аккаунта в трекере."""

    failures: int = 0
    """Число неудачных попыток с момента последнего сброса."""

    next_allowed_ts: float = 0.0
    """Unix-timestamp, до которого вход запрещён (0 = не заблокирован)."""

    last_failure_ts: float = field(default_factory=time.time)
    """Время последней неудачной попытки (для auto-reset)."""

    # Число раз, когда аккаунт блокировался (используется для определения задержки)
    lockout_count: int = 0


class LockoutTracker:
    """
    In-memory трекер попыток входа с экспоненциальным backoff.

    Алгоритм:
    1. При N-й неудаче (N >= failed_threshold) — блокировка.
    2. Задержка выбирается из delays_sec по индексу lockout_count.
    3. После reset_after_sec неактивности счётчик обнуляется.
    4. Успешный вход сбрасывает счётчик полностью.
    """

    def __init__(self, policy: LockoutPolicy) -> None:
        self._policy = policy
        self._states: dict[str, _AccountState] = {}
        self._lock = threading.Lock()

    # =========================================================================
    # Публичный API
    # =========================================================================

    def record_failure(self, username: str) -> None:
        """
        Зафиксировать неудачную попытку входа.

        Если превышен порог — устанавливает блокировку с задержкой.
        """
        with self._lock:
            state = self._get_or_create_state(username)
            now = time.time()

            # Проверяем сброс по неактивности
            if self._should_auto_reset(state, now):
                state.failures = 0
                state.lockout_count = 0
                state.next_allowed_ts = 0.0

            state.failures += 1
            state.last_failure_ts = now

            # Применяем блокировку если порог превышен
            if state.failures >= self._policy.failed_threshold:
                delay = self._policy.get_delay(state.lockout_count)
                state.next_allowed_ts = now + delay
                state.lockout_count += 1

    def record_success(self, username: str) -> None:
        """
        Зафиксировать успешный вход — сбросить все счётчики.
        """
        with self._lock:
            if username in self._states:
                del self._states[username]

    def is_locked(self, username: str) -> tuple[bool, int]:
        """
        Проверить, заблокирован ли аккаунт.

        Returns:
            (locked: bool, seconds_remaining: int)
            Если не заблокирован — (False, 0).
            Если заблокирован — (True, N) где N = секунд до разблокировки.
        """
        with self._lock:
            state = self._states.get(username)
            if state is None:
                return False, 0

            now = time.time()

            # Проверяем сброс по неактивности
            if self._should_auto_reset(state, now):
                del self._states[username]
                return False, 0

            if state.next_allowed_ts <= now:
                return False, 0

            remaining = int(state.next_allowed_ts - now)
            return True, max(remaining, 1)

    def get_failures(self, username: str) -> int:
        """
        Вернуть текущий счётчик неудачных попыток для пользователя.

        Returns:
            Число накопленных неудач (0 если записи нет или был auto-reset).
        """
        with self._lock:
            state = self._states.get(username)
            if state is None:
                return 0
            now = time.time()
            if self._should_auto_reset(state, now):
                return 0
            return state.failures

    def reset(self, username: str) -> None:
        """Принудительный сброс состояния пользователя (для тестов и admin-операций)."""
        with self._lock:
            self._states.pop(username, None)

    def reset_all(self) -> None:
        """Сброс всех состояний (для тестов)."""
        with self._lock:
            self._states.clear()

    # =========================================================================
    # Вспомогательные методы
    # =========================================================================

    def _get_or_create_state(self, username: str) -> _AccountState:
        """Получить или создать запись состояния (вызывается под локом)."""
        if username not in self._states:
            self._states[username] = _AccountState()
        return self._states[username]

    def _should_auto_reset(self, state: _AccountState, now: float) -> bool:
        """True если прошло reset_after_sec с момента последней неудачи."""
        elapsed = now - state.last_failure_ts
        return elapsed >= self._policy.reset_after_sec
