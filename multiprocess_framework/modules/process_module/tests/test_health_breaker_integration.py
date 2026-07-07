# -*- coding: utf-8 -*-
"""Интеграция HealthState ↔ CircuitBreaker (Ф2 Task 2.2).

Проверяет честную связку: N подряд ``report_error`` → breaker open → health
degraded + поле ``health.breaker == "open"``; восстановление по успеху и по
тишине (poll) снимает breaker-owned деградацию. Всё детерминировано через общий
инъецированный clock.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.health import (
    BreakerState,
    CircuitBreaker,
    HealthField,
    HealthState,
    HealthStatus,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _state(threshold: int = 3, cooldown: float = 10.0) -> tuple[HealthState, FakeClock]:
    clk = FakeClock()
    br = CircuitBreaker(fail_threshold=threshold, cooldown_sec=cooldown, clock=clk)
    return HealthState(clock=clk, breaker=br), clk


def _err(i: int = 0) -> RuntimeError:
    return RuntimeError(f"boom-{i}")


# --- открытие: N подряд report_error → degraded + breaker=open ---------------


def test_consecutive_errors_trip_breaker_and_degrade() -> None:
    hs, _ = _state(threshold=3)
    hs.report_error(_err(1), context="produce")
    hs.report_error(_err(2), context="produce")
    assert hs.status == HealthStatus.OK  # ещё не порог
    assert hs.breaker_state == BreakerState.CLOSED

    hs.report_error(_err(3), context="produce")  # 3-й → open
    assert hs.breaker_state == BreakerState.OPEN
    assert hs.status == HealthStatus.DEGRADED

    snap = hs.snapshot()
    assert snap[HealthField.BREAKER] == "open"
    assert snap[HealthField.STATUS] == "degraded"
    assert "breaker open" in (snap[HealthField.DEGRADED_REASON] or "")
    # errors — кумулятивный, монотонный (не подряд-счётчик).
    assert snap[HealthField.ERRORS] == 3


def test_errors_counter_is_cumulative_not_consecutive() -> None:
    # Успех между ошибками сбрасывает breaker, но НЕ кумулятивный errors.
    hs, _ = _state(threshold=3)
    hs.report_error(_err())
    hs.report_error(_err())
    hs.record_success()  # сброс подряд-счётчика
    hs.report_error(_err())
    hs.report_error(_err())
    assert hs.status == HealthStatus.OK  # подряд только 2 после сброса
    assert hs.error_count == 4  # но всего 4


# --- восстановление ----------------------------------------------------------


def test_success_clears_breaker_degradation() -> None:
    hs, _ = _state(threshold=2)
    hs.report_error(_err())
    hs.report_error(_err())  # open → degraded
    assert hs.status == HealthStatus.DEGRADED

    hs.record_success()  # успешная итерация
    assert hs.breaker_state == BreakerState.CLOSED
    assert hs.status == HealthStatus.OK
    assert hs.snapshot()[HealthField.DEGRADED_REASON] is None


def test_poll_passive_recovery_after_silence() -> None:
    hs, clk = _state(threshold=2, cooldown=10.0)
    hs.report_error(_err())
    hs.report_error(_err())  # open @1000
    assert hs.status == HealthStatus.DEGRADED

    hs.poll()  # тишины нет
    assert hs.breaker_state == BreakerState.OPEN

    clk.advance(11.0)
    hs.poll()  # open → half_open
    assert hs.breaker_state == BreakerState.HALF_OPEN
    assert hs.status == HealthStatus.DEGRADED  # ещё не восстановились

    clk.advance(11.0)
    hs.poll()  # half_open → closed
    assert hs.breaker_state == BreakerState.CLOSED
    assert hs.status == HealthStatus.OK


# --- не затираем чужую деградацию -------------------------------------------


def test_breaker_recovery_does_not_clear_foreign_degraded() -> None:
    # Явная деградация НЕ от breaker (напр. «сосед выпал») не должна сниматься
    # восстановлением breaker.
    hs, _ = _state(threshold=2)
    hs.set_status(HealthStatus.DEGRADED, "сосед выпал")  # чужая причина
    assert not hs.breaker_open

    # Успех закрывает breaker (он и так closed) — но чужой degraded остаётся.
    hs.record_success()
    assert hs.status == HealthStatus.DEGRADED
    assert hs.snapshot()[HealthField.DEGRADED_REASON] == "сосед выпал"


def test_half_open_reopens_on_new_error() -> None:
    hs, clk = _state(threshold=1, cooldown=5.0)
    hs.report_error(_err())  # open
    clk.advance(6.0)
    hs.poll()  # half_open
    assert hs.breaker_state == BreakerState.HALF_OPEN
    hs.report_error(_err())  # проба провалилась → снова open
    assert hs.breaker_state == BreakerState.OPEN
    assert hs.status == HealthStatus.DEGRADED


# --- лог-only режим ----------------------------------------------------------


def test_log_only_still_counts_but_does_not_publish_dirty() -> None:
    # В лог-only breaker всё равно честно считает (для наблюдаемости в логах),
    # но state-дерево не пачкается: take_dirty после отчётов не публикует.
    clk = FakeClock()
    br = CircuitBreaker(fail_threshold=2, clock=clk)
    hs = HealthState(clock=clk, log_only=True, breaker=br)
    hs.take_dirty()  # снять стартовый dirty
    hs.report_error(_err())
    hs.report_error(_err())  # breaker open, но log_only
    # errors инкрементится всегда (честность), breaker открыт.
    assert hs.error_count == 2
    # set_status под log_only меняет статус в памяти, но dirty не поднимает.
    assert hs.take_dirty() is None
