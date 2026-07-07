# -*- coding: utf-8 -*-
"""Юниты CircuitBreaker — честный breaker подряд-ошибок (Ф2 Task 2.2).

Детерминизм — через инъекцию clock: тесты сами двигают «время», реальный sleep
не нужен.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.health.breaker import (
    BreakerState,
    CircuitBreaker,
)


class FakeClock:
    """Управляемые часы: t стартует с 0, двигается вручную."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _breaker(threshold: int = 3, cooldown: float = 10.0) -> tuple[CircuitBreaker, FakeClock]:
    clk = FakeClock()
    return CircuitBreaker(fail_threshold=threshold, cooldown_sec=cooldown, clock=clk), clk


# --- открытие по порогу ---------------------------------------------------


def test_starts_closed() -> None:
    br, _ = _breaker()
    assert br.state == BreakerState.CLOSED
    assert not br.is_open
    assert br.consecutive == 0


def test_opens_on_consecutive_threshold() -> None:
    br, _ = _breaker(threshold=3)
    assert br.record_failure() is None  # 1
    assert br.record_failure() is None  # 2
    assert br.record_failure() == BreakerState.OPEN  # 3 → open
    assert br.state == BreakerState.OPEN
    assert br.is_open
    assert br.consecutive == 3


def test_below_threshold_stays_closed() -> None:
    br, _ = _breaker(threshold=5)
    for _ in range(4):
        assert br.record_failure() is None
    assert br.state == BreakerState.CLOSED


def test_threshold_one_opens_immediately() -> None:
    br, _ = _breaker(threshold=1)
    assert br.record_failure() == BreakerState.OPEN


def test_threshold_floor_is_one() -> None:
    # Порог < 1 нормализуется в 1 (иначе breaker никогда бы не открылся).
    br = CircuitBreaker(fail_threshold=0)
    assert br.threshold == 1


# --- сброс по успеху ------------------------------------------------------


def test_success_resets_consecutive_when_closed() -> None:
    br, _ = _breaker(threshold=3)
    br.record_failure()
    br.record_failure()
    assert br.record_success() is None  # ещё closed, перехода нет
    assert br.consecutive == 0
    # Счётчик реально обнулён — снова нужно 3 подряд.
    assert br.record_failure() is None
    assert br.record_failure() is None
    assert br.record_failure() == BreakerState.OPEN


def test_success_closes_open_breaker() -> None:
    br, _ = _breaker(threshold=2)
    br.record_failure()
    br.record_failure()  # open
    assert br.state == BreakerState.OPEN
    assert br.record_success() == BreakerState.CLOSED
    assert br.state == BreakerState.CLOSED
    assert br.consecutive == 0


# --- восстановление по тишине (poll) --------------------------------------


def test_poll_noop_when_closed() -> None:
    br, clk = _breaker()
    clk.advance(1000)
    assert br.poll() is None


def test_open_to_half_open_after_cooldown() -> None:
    br, clk = _breaker(threshold=2, cooldown=10.0)
    br.record_failure()
    br.record_failure()  # open @ t=0
    assert br.poll() is None  # тишины ещё нет
    clk.advance(9.0)
    assert br.poll() is None  # 9 < 10
    clk.advance(2.0)  # t=11, тишина 11 >= 10
    assert br.poll() == BreakerState.HALF_OPEN
    assert br.state == BreakerState.HALF_OPEN


def test_half_open_to_closed_after_more_silence() -> None:
    br, clk = _breaker(threshold=1, cooldown=5.0)
    br.record_failure()  # open @0
    clk.advance(5.0)
    assert br.poll() == BreakerState.HALF_OPEN  # half @5, last_fail сдвинут на 5
    clk.advance(4.0)
    assert br.poll() is None  # 9-5=4 < 5
    clk.advance(2.0)  # t=11, тишина 6 >= 5
    assert br.poll() == BreakerState.CLOSED
    assert br.state == BreakerState.CLOSED


def test_half_open_reopens_on_failure() -> None:
    br, clk = _breaker(threshold=1, cooldown=5.0)
    br.record_failure()  # open
    clk.advance(6.0)
    assert br.poll() == BreakerState.HALF_OPEN
    # Проба провалилась — сразу снова open (не ждём порог).
    assert br.record_failure() == BreakerState.OPEN
    assert br.state == BreakerState.OPEN


def test_half_open_closes_on_success() -> None:
    br, clk = _breaker(threshold=1, cooldown=5.0)
    br.record_failure()  # open
    clk.advance(6.0)
    br.poll()  # half_open
    assert br.record_success() == BreakerState.CLOSED


# --- разное ---------------------------------------------------------------


def test_open_stays_open_on_further_failures_no_transition() -> None:
    br, _ = _breaker(threshold=2)
    br.record_failure()
    br.record_failure()  # open
    assert br.record_failure() is None  # уже open — перехода нет
    assert br.consecutive == 3  # но счётчик копится (видимость)


def test_snapshot_shape() -> None:
    br, _ = _breaker(threshold=4, cooldown=7.5)
    br.record_failure()
    snap = br.snapshot()
    assert snap == {
        "state": BreakerState.CLOSED,
        "consecutive": 1,
        "threshold": 4,
        "cooldown_sec": 7.5,
    }
