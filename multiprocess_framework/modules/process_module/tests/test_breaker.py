# -*- coding: utf-8 -*-
"""Юнит-тесты примитива CircuitBreaker (Ф2 Task 2.2).

Проверяют: порог размыкания, сброс серии по успеху, cooldown/half-open,
провал пробы в half-open, callback'и on_open/on_close, ручной reset и снапшот.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.health.breaker import (
    BreakerState,
    CircuitBreaker,
)


class _Clock:
    """Управляемое монотонное время для детерминизма cooldown-тестов."""

    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


# --- порог / серия ----------------------------------------------------------


def test_opens_on_threshold() -> None:
    br = CircuitBreaker(threshold=3)
    assert br.record_failure() is False  # 1
    assert br.record_failure() is False  # 2
    assert br.record_failure() is True  # 3 → OPEN именно сейчас
    assert br.is_open is True
    assert br.state is BreakerState.OPEN
    assert br.consecutive == 3


def test_success_resets_series_before_threshold() -> None:
    br = CircuitBreaker(threshold=3)
    br.record_failure()
    br.record_failure()
    assert br.record_success() is False  # закрыт был → закрыт остался
    assert br.consecutive == 0
    # Серия обнулена: снова нужно 3 подряд.
    assert br.record_failure() is False
    assert br.record_failure() is False
    assert br.record_failure() is True


def test_failure_after_open_does_not_refire() -> None:
    br = CircuitBreaker(threshold=2)
    br.record_failure()
    assert br.record_failure() is True  # OPEN
    # Дальнейшие фейлы в OPEN не «размыкают снова» (уже разомкнут).
    assert br.record_failure() is False
    assert br.is_open is True


# --- cooldown / half-open ---------------------------------------------------


def test_allow_gated_until_cooldown() -> None:
    clock = _Clock()
    br = CircuitBreaker(threshold=1, cooldown_sec=10.0, clock=clock)
    br.record_failure()  # OPEN, opened_at=100
    assert br.allow() is False  # cooldown не истёк
    clock.t = 105.0
    assert br.allow() is False
    clock.t = 110.0
    assert br.allow() is True  # cooldown истёк → HALF_OPEN проба
    assert br.state is BreakerState.HALF_OPEN


def test_halfopen_success_closes() -> None:
    clock = _Clock()
    br = CircuitBreaker(threshold=1, cooldown_sec=10.0, clock=clock)
    br.record_failure()
    clock.t = 110.0
    br.allow()  # → HALF_OPEN
    assert br.record_success() is True  # проба удалась → CLOSED
    assert br.state is BreakerState.CLOSED
    assert br.is_open is False


def test_halfopen_failure_reopens_and_resets_cooldown() -> None:
    clock = _Clock()
    br = CircuitBreaker(threshold=1, cooldown_sec=10.0, clock=clock)
    br.record_failure()
    clock.t = 110.0
    br.allow()  # HALF_OPEN
    br.record_failure()  # проба провалилась → снова OPEN, opened_at=110
    assert br.state is BreakerState.OPEN
    assert br.allow() is False  # cooldown отсчитывается заново
    clock.t = 120.0
    assert br.allow() is True


# --- callbacks --------------------------------------------------------------


def test_callbacks_fire_on_transition() -> None:
    events: list[str] = []
    br = CircuitBreaker(
        threshold=2,
        on_open=lambda b: events.append(f"open:{b.consecutive}"),
        on_close=lambda b: events.append("close"),
    )
    br.record_failure()
    br.record_failure()  # open
    br.record_success()  # close
    br.record_success()  # уже закрыт → без close
    assert events == ["open:2", "close"]


# --- reset / snapshot -------------------------------------------------------


def test_reset_forces_closed_without_callback() -> None:
    closed: list[int] = []
    br = CircuitBreaker(threshold=1, on_close=lambda b: closed.append(1))
    br.record_failure()  # OPEN
    br.reset()
    assert br.state is BreakerState.CLOSED
    assert br.consecutive == 0
    assert closed == []  # reset не зовёт on_close


def test_snapshot_shape() -> None:
    br = CircuitBreaker(threshold=2)
    br.record_failure()
    br.record_failure()  # trip
    snap = br.snapshot()
    assert snap == {"state": "open", "consecutive": 2, "threshold": 2, "trips": 1}
