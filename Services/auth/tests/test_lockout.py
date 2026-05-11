# -*- coding: utf-8 -*-
"""
Тесты LockoutTracker.

Проверяют: последовательность задержек, reset_after_sec, thread-safety.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from Services.auth import LockoutPolicy, LockoutTracker


@pytest.fixture
def policy() -> LockoutPolicy:
    """Быстрая политика для тестов: threshold=3, reset=5s, delays=[1,2,4]."""
    return LockoutPolicy(
        failed_threshold=3,
        reset_after_sec=5,
        delays_sec=[1, 2, 4],
    )


@pytest.fixture
def tracker(policy: LockoutPolicy) -> LockoutTracker:
    return LockoutTracker(policy)


# =============================================================================
# Базовые сценарии
# =============================================================================


def test_no_failures_not_locked(tracker: LockoutTracker) -> None:
    """Без неудач аккаунт не заблокирован."""
    locked, wait = tracker.is_locked("alice")
    assert locked is False
    assert wait == 0


def test_below_threshold_not_locked(tracker: LockoutTracker) -> None:
    """Меньше threshold неудач — не заблокирован."""
    tracker.record_failure("alice")
    tracker.record_failure("alice")
    locked, wait = tracker.is_locked("alice")
    assert locked is False


def test_at_threshold_becomes_locked(tracker: LockoutTracker) -> None:
    """При threshold неудачах — блокировка."""
    for _ in range(3):  # threshold=3
        tracker.record_failure("alice")
    locked, wait = tracker.is_locked("alice")
    assert locked is True
    assert wait > 0


def test_first_lockout_delay(tracker: LockoutTracker) -> None:
    """Первая блокировка использует delays_sec[0]."""
    for _ in range(3):
        tracker.record_failure("alice")
    locked, wait = tracker.is_locked("alice")
    assert locked is True
    assert wait <= 1  # delays_sec[0]=1, time может немного пройти


def test_second_lockout_larger_delay(tracker: LockoutTracker) -> None:
    """Вторая блокировка использует больший delays_sec."""
    policy_short = LockoutPolicy(
        failed_threshold=2,
        reset_after_sec=3600,
        delays_sec=[0, 10],
    )
    t = LockoutTracker(policy_short)

    # Первая блокировка (delay=0 → разблокирован немедленно, но lockout_count=1)
    t.record_failure("bob")
    t.record_failure("bob")  # locks with delay=0

    # Ещё одна неудача → вторая блокировка (delay=10)
    t.record_failure("bob")
    locked, wait = t.is_locked("bob")
    # delay=10, должен быть заблокирован
    assert locked is True
    assert wait > 0


def test_success_resets_state(tracker: LockoutTracker) -> None:
    """record_success сбрасывает блокировку."""
    for _ in range(3):
        tracker.record_failure("alice")
    assert tracker.is_locked("alice")[0] is True

    tracker.record_success("alice")
    locked, wait = tracker.is_locked("alice")
    assert locked is False
    assert wait == 0


def test_different_users_independent(tracker: LockoutTracker) -> None:
    """Блокировка одного пользователя не влияет на другого."""
    for _ in range(3):
        tracker.record_failure("alice")
    locked_alice, _ = tracker.is_locked("alice")
    locked_bob, _ = tracker.is_locked("bob")
    assert locked_alice is True
    assert locked_bob is False


# =============================================================================
# reset_after_sec — авто-сброс по неактивности
# =============================================================================


def test_auto_reset_after_inactivity(tracker: LockoutTracker) -> None:
    """После reset_after_sec неактивности счётчик обнуляется."""
    tracker.record_failure("alice")
    tracker.record_failure("alice")

    # Эмулируем прошедшее время: подменяем time.time в трекере
    future_time = time.time() + 10  # 10s > reset_after_sec=5

    with patch("Services.auth.security.lockout.time") as mock_time:
        mock_time.time.return_value = future_time
        locked, wait = tracker.is_locked("alice")

    assert locked is False


def test_auto_reset_clears_on_is_locked(tracker: LockoutTracker) -> None:
    """is_locked очищает запись при авто-сбросе."""
    for _ in range(3):
        tracker.record_failure("alice")

    future = time.time() + 100

    with patch("Services.auth.security.lockout.time") as mock_time:
        mock_time.time.return_value = future
        locked, _ = tracker.is_locked("alice")

    assert locked is False


# =============================================================================
# Thread-safety smoke test
# =============================================================================


def test_thread_safety_no_exception(tracker: LockoutTracker) -> None:
    """Параллельные record_failure/is_locked не вызывают исключений."""
    errors: list[Exception] = []

    def worker(username: str) -> None:
        try:
            for _ in range(20):
                tracker.record_failure(username)
                tracker.is_locked(username)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"user_{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Ошибки в потоках: {errors}"


def test_thread_safety_shared_user() -> None:
    """Параллельные операции над одним пользователем — без гонок."""
    policy = LockoutPolicy(failed_threshold=5, reset_after_sec=3600, delays_sec=[1, 2])
    tracker = LockoutTracker(policy)
    errors: list[Exception] = []
    results: list[tuple[bool, int]] = []
    lock = threading.Lock()

    def record_and_check() -> None:
        try:
            tracker.record_failure("shared_user")
            result = tracker.is_locked("shared_user")
            with lock:
                results.append(result)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=record_and_check) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # Все результаты — корректные tuple (bool, int)
    for locked, wait in results:
        assert isinstance(locked, bool)
        assert isinstance(wait, int)
        assert wait >= 0


# =============================================================================
# Explicit reset и reset_all
# =============================================================================


def test_explicit_reset(tracker: LockoutTracker) -> None:
    """reset() сбрасывает состояние конкретного пользователя."""
    for _ in range(3):
        tracker.record_failure("alice")
    tracker.reset("alice")
    assert tracker.is_locked("alice")[0] is False


def test_reset_all(tracker: LockoutTracker) -> None:
    """reset_all() сбрасывает состояние всех пользователей."""
    for _ in range(3):
        tracker.record_failure("alice")
        tracker.record_failure("bob")
    tracker.reset_all()
    assert tracker.is_locked("alice")[0] is False
    assert tracker.is_locked("bob")[0] is False
