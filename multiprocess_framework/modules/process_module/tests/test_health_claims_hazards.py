# -*- coding: utf-8 -*-
"""Сторожа автора C-66: заявки владельцев деградации, H1–H12 (ADR-PM-058).

Слепая приёмка — ``test_health_claims_acceptance.py``. Здесь то, что она не видит: гонка,
режим ``log_only``, журнал и dirty при неизменном эффективном значении, порядок заявок.
Объекты настоящие, часы подставные, порог breaker (5) и cooldown (30 с) по умолчанию.
Ожидаемые значения — литералы. Гонка H1 идёт в daemon-потоках с дедлайном ``join``.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable

import pytest

from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState
from multiprocess_framework.modules.process_module.health.breaker import CircuitBreaker

_DEADLINE_S = 10.0
_ITERATIONS = 1000
_MIN_OPENS_IN_RACE = 50
_STATUS_LINE = "[health] status →"


class _Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _make(*, log_only: bool = False) -> tuple[HealthState, _Clock, HealthReporter, HealthReporter, list[str]]:
    clock = _Clock()
    lines: list[str] = []
    state = HealthState(clock=clock, log=lines.append, log_only=log_only)
    return state, clock, HealthReporter(state, source="A"), HealthReporter(state, source="B"), lines


def _trip(state: HealthState) -> None:
    for i in range(5):
        state.report_error(RuntimeError(f"x{i}"), context="load")


def _count_opens(state: HealthState) -> list[int]:
    """Считать переходы breaker в `open`: каждый ставит заявку breaker."""
    opens: list[int] = []
    real_record_failure = state._breaker.record_failure

    def _counting() -> str | None:
        transition = real_record_failure()
        if transition == "open":
            opens.append(1)
        return transition

    state._breaker.record_failure = _counting  # type: ignore[method-assign]
    return opens


def _leave_stale_claim(state: HealthState) -> None:
    """Гонка: `record_success` сразу после открытия, до `set_status`; заявка остаётся при `closed`."""
    real_record_failure = state._breaker.record_failure

    def _success_right_after_open() -> str | None:
        transition = real_record_failure()
        if transition == "open":
            state.record_success()
        return transition

    state._breaker.record_failure = _success_right_after_open  # type: ignore[method-assign]
    _trip(state)
    state._breaker.record_failure = real_record_failure  # type: ignore[method-assign]


def _status_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith(_STATUS_LINE)]


def _view(state: HealthState) -> tuple[str, str | None, str]:
    snap = state.snapshot()
    return snap["status"], snap["degraded_reason"], snap["breaker"]


# --- H1: гонка ----------------------------------------------------------------


def test_h1_race_of_owners_and_breaker_ends_clean() -> None:
    """Два потока «трип, record_success» и два владельца `degraded`/`ok`: заявка breaker всё время
    ставится и снимается; ни зависания, ни потерянного факта, итог чистый после такта `poll`."""
    state, _clock, a, b, _lines = _make()
    opens = _count_opens(state)
    barrier = threading.Barrier(4, timeout=_DEADLINE_S)
    errors: list[BaseException] = []

    def _worker(step: Callable[[], None], iterations: int) -> None:
        try:
            barrier.wait()
            for _ in range(iterations):
                step()
        except BaseException as exc:  # noqa: BLE001 — отдаём в поток теста без потерь
            errors.append(exc)

    def _claim(owner: HealthReporter, reason: str) -> Callable[[], None]:
        def _step() -> None:
            owner.degraded(reason)
            owner.ok()

        return _step

    def _trip_and_recover() -> None:
        _trip(state)
        state.record_success()

    work = [
        (_trip_and_recover, 200),
        (_trip_and_recover, 200),
        (_claim(a, "a"), _ITERATIONS),
        (_claim(b, "b"), _ITERATIONS),
    ]
    threads = [threading.Thread(target=_worker, args=item, daemon=True) for item in work]

    previous_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-5)  # чаще переключать потоки: иначе окно гонки почти не открывается
    try:
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + _DEADLINE_S
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
    finally:
        sys.setswitchinterval(previous_interval)

    if any(thread.is_alive() for thread in threads):
        pytest.fail(f"потоки не завершились за {_DEADLINE_S} с (взаимная блокировка?)")
    assert errors == []
    assert state.error_count == 2000
    assert len(opens) >= _MIN_OPENS_IN_RACE, f"заявка breaker ставилась {len(opens)} раз: гонка не проверена"

    state.poll()  # такт heartbeat: снимает заявку, которую гонка оставила при закрытом breaker (H8)

    assert _view(state) == ("ok", None, "closed")


# --- H2: log_only -------------------------------------------------------------


def test_h2_log_only_counts_claim_without_publishing() -> None:
    """В `log_only` заявка считается, а публикация и `updated_at` не трогаются."""
    state, _clock, a, _b, _lines = _make(log_only=True)
    state.take_dirty()  # __init__ поднимает dirty и в log_only: начальный снимок сливаем

    a.degraded("assets")

    assert _view(state) == ("degraded", "assets", "closed")
    assert state.take_dirty() is None
    assert state.snapshot()["updated_at"] == 0.0


# --- H3: журнал по изменению эффективного значения ------------------------------


def test_h3_breaker_close_under_later_claim_writes_no_status_line() -> None:
    """Порядок (б): закрытие снимает заявку breaker, показанное значение не меняется — строки нет."""
    state, clock, a, _b, lines = _make()

    _trip(state)
    a.degraded("assets")
    assert len(_status_lines(lines)) == 2

    clock.advance(62.0)
    state.poll()
    clock.advance(62.0)
    state.poll()

    assert state.snapshot()["breaker"] == "closed"
    assert len(_status_lines(lines)) == 2


# --- H4: повторная постановка с новой причиной ----------------------------------


def test_h4_reassert_with_new_reason_moves_claim_to_the_end() -> None:
    """Новая причина делает заявку самой поздней; `ok` открывает заявку соседа."""
    state, _clock, a, b, lines = _make()

    a.degraded("a1")
    b.degraded("b")
    a.degraded("a2")

    assert state.snapshot()["degraded_reason"] == "a2"
    assert _status_lines(lines)[-1] == "[health] status → degraded: a2"

    a.ok()

    assert state.snapshot()["degraded_reason"] == "b"


# --- H5: прежний контракт ok("текст") -------------------------------------------


def test_h5_ok_with_text_keeps_reason_when_no_claims() -> None:
    """`ok("текст")` без заявок: статус `ok`, причина — этот текст."""
    state, _clock, _a, _b, _lines = _make()

    state.ok("recovered")

    assert _view(state) == ("ok", "recovered", "closed")


# --- H6: dirty при закрытии, значение не менялось -------------------------------


def test_h6_breaker_close_raises_dirty_when_effective_value_is_unchanged() -> None:
    """Порядок (б): dirty при закрытии поднимает только `_mark_dirty`, снимок несёт `breaker: closed`."""
    state, clock, a, _b, _lines = _make()

    _trip(state)
    a.degraded("assets")
    state.take_dirty()

    clock.advance(62.0)
    state.poll()
    assert state.snapshot()["breaker"] == "half_open"
    state.take_dirty()  # иначе dirty от half_open замаскирует снятие `_mark_dirty` на закрытии

    clock.advance(62.0)
    state.poll()
    snap = state.take_dirty()

    assert snap is not None
    assert snap["status"] == "degraded"
    assert snap["degraded_reason"] == "assets"
    assert snap["breaker"] == "closed"


# --- H7: чередование повторов --------------------------------------------------


def test_h7_alternating_repeats_do_not_move_claims() -> None:
    """Две заявки на тике: повтор тех же значений не меняет ни причину, ни журнал, ни публикацию."""
    state, clock, a, b, lines = _make()

    a.degraded("a")
    b.degraded("b")
    state.take_dirty()
    updated_at = state.snapshot()["updated_at"]
    lines_before = len(lines)

    for _ in range(4):
        clock.advance(1.0)  # часы идут: `updated_at` обязан стоять из-за правила, а не из-за часов
        a.degraded("a")
        assert state.snapshot()["degraded_reason"] == "b"
        b.degraded("b")
        assert state.snapshot()["degraded_reason"] == "b"

    assert len(lines) == lines_before
    assert state.snapshot()["updated_at"] == updated_at
    assert state.take_dirty() is None


# --- H8: заявка breaker при закрытом breaker -----------------------------------


def test_h8_stale_breaker_claim_released_by_next_poll() -> None:
    """Гонка: `record_success` между возвратом `record_failure` и `set_status` оставляет заявку;
    снять её может только breaker, и делает это следующий такт `poll`."""
    state, _clock, a, _b, _lines = _make()
    _leave_stale_claim(state)

    stale = ("degraded", "breaker open: RuntimeError @ load ×5 подряд", "closed")
    assert _view(state) == stale
    a.ok()
    state.ok()
    assert _view(state) == stale  # чужой `ok` заявку breaker не снимает

    state.poll()

    assert _view(state) == ("ok", None, "closed")


def test_h8_poll_keeps_plugin_claim_when_releasing_stale_breaker_claim() -> None:
    """Такт `poll` снимает только заявку breaker: заявка плагина остаётся на виду."""
    state, _clock, a, _b, _lines = _make()
    a.degraded("assets")
    _leave_stale_claim(state)

    state.poll()

    assert _view(state) == ("degraded", "assets", "closed")


# --- H9: пока breaker не закрыт, заявка на месте --------------------------------


def test_h9_breaker_claim_stays_until_closed() -> None:
    """`open` и `half_open`: холостой `poll` заявку breaker не снимает."""
    state, clock, _a, _b, _lines = _make()
    reason = "breaker open: RuntimeError @ load ×5 подряд"

    _trip(state)
    state.poll()  # cooldown не вышел: переход не случился, breaker `open`
    assert _view(state) == ("degraded", reason, "open")

    clock.advance(62.0)
    state.poll()
    assert _view(state) == ("degraded", reason, "half_open")

    state.poll()  # точка отсчёта сдвинута: переход не случился, breaker `half_open`
    assert _view(state) == ("degraded", reason, "half_open")


# --- H10: холостой poll ничего не пишет -----------------------------------------


def test_h10_idle_poll_writes_nothing() -> None:
    """1000 холостых `poll` без заявок: ни dirty, ни `updated_at`, ни строк журнала."""
    state, clock, _a, _b, lines = _make()
    state.take_dirty()

    for _ in range(1000):
        clock.advance(1.0)
        state.poll()

    assert state.take_dirty() is None
    assert state.snapshot()["updated_at"] == 0.0
    assert lines == []


def test_h10_idle_poll_keeps_ok_text() -> None:
    """Холостой `poll` не стирает текст `ok("текст")`: заявки breaker нет, снимать нечего."""
    state, clock, _a, _b, lines = _make()
    state.ok("recovered")
    state.take_dirty()
    lines_before = len(lines)

    clock.advance(1.0)
    state.poll()

    assert _view(state) == ("ok", "recovered", "closed")
    assert state.take_dirty() is None
    assert len(lines) == lines_before


# --- H11: failed через фасад плагина --------------------------------------------


def test_h11_plugin_failed_released_by_own_ok() -> None:
    """`failed` плагина идёт под его именем: его же `ok` заявку снимает."""
    state, _clock, a, _b, _lines = _make()

    a.failed("f")
    assert _view(state) == ("failed", "f", "closed")
    a.ok()

    assert _view(state) == ("ok", None, "closed")


def test_h11_plugin_failed_survives_breaker_cycle_and_released_by_own_ok() -> None:
    """Цикл открытия и закрытия breaker `failed` плагина не трогает; снимает его `ok` плагина."""
    state, clock, a, _b, _lines = _make()

    a.failed("f")
    _trip(state)
    clock.advance(62.0)
    state.poll()
    clock.advance(62.0)
    state.poll()
    assert _view(state) == ("failed", "f", "closed")

    a.ok()

    assert _view(state) == ("ok", None, "closed")


# --- H12: трип в щели между проверкой и снятием ---------------------------------


class _ReadHookBreaker(CircuitBreaker):
    """Первое чтение `state` после взвода зовёт `on_read` и отдаёт `closed`, прочитанное до трипа."""

    on_read: Callable[[], None] | None = None

    @property
    def state(self) -> str:
        hook, self.on_read = self.on_read, None
        if hook is None:
            return self._state
        hook()
        return "closed"


def test_h12_trip_between_check_and_release_keeps_breaker_claim() -> None:
    """Залипшая заявка, breaker закрыт, такт `poll` прочитал `closed`, другой поток трипнул в щели.

    Снятие без замка давало `ok` при `open`, и шторм ошибок держал этот ложно-здоровый статус:
    `poll` не доходил до `half_open`, заявка не возвращалась.
    """
    clock = _Clock()
    in_track = threading.Event()
    go = threading.Event()
    claim_done = threading.Event()
    tripper: list[threading.Thread] = []
    tracked = [0]

    def _track(_exc: BaseException, _payload: object = None) -> None:
        if threading.current_thread() is not tripper[0]:
            return
        tracked[0] += 1
        if tracked[0] == 5:  # пятая ошибка: `_safe_track` идёт раньше `record_failure`
            in_track.set()
            go.wait(_DEADLINE_S)

    breaker = _ReadHookBreaker(fail_threshold=5, cooldown_sec=30.0, clock=clock)
    state = HealthState(clock=clock, track=_track, breaker=breaker, log_only=False)
    tripper.append(threading.Thread(target=_trip, args=(state,), daemon=True))  # счёт `_track` только его
    _leave_stale_claim(state)
    assert _view(state) == ("degraded", "breaker open: RuntimeError @ load ×5 подряд", "closed")

    real_set_status = state.set_status

    def _set_status(status: object, reason: str | None = None, *, owner: str = "") -> None:
        real_set_status(status, reason, owner=owner)
        if status == "degraded":
            claim_done.set()

    state.set_status = _set_status  # type: ignore[method-assign,assignment]

    def _on_read() -> None:
        go.set()
        deadline = time.monotonic() + _DEADLINE_S
        while breaker._state != "open" and time.monotonic() < deadline:
            time.sleep(0.001)
        # Снятие без замка: заявка трипа успевает встать, и снятие сносит её. Под замком `set_status`
        # трипа ждёт конца снятия, поэтому ждать его нельзя: срок, а не бесконечное ожидание.
        claim_done.wait(0.3)

    tripper[0].start()
    assert in_track.wait(_DEADLINE_S), "поток-трип не дошёл до пятой ошибки"
    breaker.on_read = _on_read
    poller = threading.Thread(target=state.poll, daemon=True)
    poller.start()

    deadline = time.monotonic() + _DEADLINE_S
    for thread in (poller, tripper[0]):
        thread.join(max(0.0, deadline - time.monotonic()))
    if poller.is_alive() or tripper[0].is_alive():
        pytest.fail(f"потоки не завершились за {_DEADLINE_S} с (взаимная блокировка?)")

    assert _view(state) == ("degraded", "breaker open: RuntimeError @ load ×5 подряд", "open")


@pytest.mark.parametrize("close", ["record_success", "poll"])
def test_h12_trip_during_close_keeps_breaker_claim(close: str) -> None:
    """`fail_threshold=1`: ошибка между переходом в `closed` и снятием заново открывает breaker."""
    clock = _Clock()
    breaker = CircuitBreaker(fail_threshold=1, cooldown_sec=30.0, clock=clock)
    state = HealthState(clock=clock, breaker=breaker, log_only=False)
    state.report_error(RuntimeError("x"), context="load")
    if close == "poll":
        clock.advance(62.0)
        state.poll()
        assert state.snapshot()["breaker"] == "half_open"

    real_mark_dirty = state._mark_dirty

    def _trip_in_the_gap() -> None:  # `_mark_dirty` идёт между переходом и снятием заявки
        state._mark_dirty = real_mark_dirty  # type: ignore[method-assign]
        real_mark_dirty()
        state.report_error(RuntimeError("x"), context="load")

    state._mark_dirty = _trip_in_the_gap  # type: ignore[method-assign]
    if close == "poll":
        clock.advance(62.0)
        state.poll()
    else:
        state.record_success()

    assert _view(state) == ("degraded", "breaker open: RuntimeError @ load ×1 подряд", "open")
