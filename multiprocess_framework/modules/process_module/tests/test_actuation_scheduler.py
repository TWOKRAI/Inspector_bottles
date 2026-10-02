# -*- coding: utf-8 -*-
"""Task 5.2 — слепые приёмочные тесты ``ActuationScheduler`` (планировщик привода).

Источник — только раздел «Task 5.2» плана ``plans/transport-single-policy/phase-5.md``
(Дизайн + Acceptance). Реализации на момент написания нет; тесты красные по построению.

Контракт, который пинят тесты:

* ``ActuationScheduler(fire, *, clock=time.time, tolerance_s=0.020)``; ``fire(payload, count)``;
* ``schedule(fire_at, window_end, count, payload) -> "scheduled" | "missed"``:
  ``now > window_end + tolerance_s`` -> ``missed_items += count``, в heap не ставится;
  иначе ``fire_at = max(fire_at, now)``, постановка;
* ``tick() -> int`` стреляет все ``fire_at <= now``; ``late_fires += 1``, если
  ``now - fire_at > tolerance_s``; ``fired_items += count``; возвращает число выстрелов;
* ``pending()`` — записей в heap; ``stats()`` — ``fired_items``, ``missed_items``,
  ``late_fires``, ``unfired_on_stop_items``;
* ``run_loop(stop_event, pause_event)``: на стопе невыстреленное не стреляет,
  ``unfired_on_stop_items += count``, heap очищается; ``fire`` вызывается ВНЕ ``Condition``.

Все времена — подменные часы. Границы ``tolerance`` берутся двоично-точными (0.25 / 100.0 / 99.75),
чтобы сравнение ``>`` против ``>=`` решало исход, а не округление float. Живые часы — только в
двух тестах (дефолтные часы и пробуждение ``run_loop`` по ``schedule``) и только с запасом
далеко выше сетки 15.6 мс Windows.

Импорт класса — внутри теста (``_make``): иначе отсутствие модуля роняло бы ВЕСЬ файл на сборке
одной ошибкой, а не каждый тест своей.

Любой вызов, способный блокироваться (``run_loop``, медленный ``fire``), идёт в daemon-потоке
с дедлайном на ``join``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, List, Tuple

T0 = 100.0  # двоично-точное «сейчас» подменных часов


class FakeClock:
    """Подменные часы: ``now`` двигает тест, не время."""

    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class Recorder:
    """``fire``-колбэк: пишет (payload, count, момент по часам)."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        self.clock = clock
        self.calls: List[Tuple[Any, int, float | None]] = []

    def __call__(self, payload: Any, count: int) -> None:
        self.calls.append((payload, count, self.clock.now if self.clock else None))

    @property
    def payloads(self) -> list:
        return [c[0] for c in self.calls]


def _make(fire: Callable[[Any, int], None], clock: Callable[[], float] | None = None, **kwargs: Any):
    """Создать планировщик; импорт здесь, чтобы красный был у каждого теста свой."""
    from multiprocess_framework.modules.process_module.generic.actuation_scheduler import ActuationScheduler

    if clock is not None:
        kwargs["clock"] = clock
    return ActuationScheduler(fire, **kwargs)


def _bounded(fn: Callable[[], Any], timeout: float = 5.0) -> Any:
    """Вызов в daemon-потоке с дедлайном на join: зависание = падение, а не висящий прогон."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - пробросим в поток теста
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"вызов завис дольше {timeout} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


# --- Окно выстрела -------------------------------------------------------------------------------


def test_scheduled_target_does_not_fire_before_fire_at_and_fires_at_it() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)

    fire_at = T0 + 0.100
    assert sch.schedule(fire_at, fire_at, 1, "p") == "scheduled"

    clock.now = fire_at - 0.001
    assert sch.tick() == 0
    assert rec.calls == []

    clock.now = fire_at  # граница включительно: fire_at <= now
    assert sch.tick() == 1
    assert [(p, c) for p, c, _ in rec.calls] == [("p", 1)]


def test_target_fires_inside_window_fire_at_plus_2ms() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)
    fire_at = T0 + 0.100
    sch.schedule(fire_at, fire_at, 1, "p")

    clock.now = fire_at + 0.001  # планировщик «проснулся» на 1 мс позже цели
    sch.tick()

    assert len(rec.calls) == 1
    fired_at = rec.calls[0][2]
    assert fire_at <= fired_at <= fire_at + 0.002


def test_target_in_the_past_but_within_tolerance_fires_on_the_next_tick_and_is_not_late() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)  # tolerance по умолчанию 0.020

    # цель опоздала на 10 мс: now <= window_end + 0.020 -> ставится; fire_at = max(fire_at, now)
    assert sch.schedule(T0 - 0.010, T0 - 0.010, 1, "p") == "scheduled"
    assert sch.pending() == 1

    assert sch.tick() == 1
    # опоздание «до постановки» — не опоздание планировщика: fire_at подтянут к now
    assert sch.stats()["late_fires"] == 0


def test_each_entry_fires_exactly_once() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)
    sch.schedule(T0 + 0.1, T0 + 0.1, 1, "p")

    clock.now = T0 + 0.1
    assert sch.tick() == 1
    clock.now = T0 + 5.0
    assert sch.tick() == 0

    assert len(rec.calls) == 1


def test_tick_fires_due_entries_in_fire_at_order_and_leaves_the_future_ones() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)
    sch.schedule(T0 + 0.3, T0 + 0.3, 1, "c")
    sch.schedule(T0 + 0.1, T0 + 0.1, 1, "a")
    sch.schedule(T0 + 0.2, T0 + 0.2, 1, "b")
    sch.schedule(T0 + 9.0, T0 + 9.0, 1, "z")

    clock.now = T0 + 0.3
    assert sch.tick() == 3

    assert rec.payloads == ["a", "b", "c"]
    assert sch.pending() == 1


# --- missed на постановке ------------------------------------------------------------------------


def test_stale_target_is_missed_on_schedule_and_never_fires() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)  # tolerance по умолчанию 0.020

    # window_end на 21 мс позади «сейчас»: now > window_end + 0.020
    assert sch.schedule(T0 - 0.021, T0 - 0.021, 1, "p") == "missed"

    assert sch.stats()["missed_items"] == 1
    assert sch.pending() == 0
    clock.now = T0 + 10.0
    assert sch.tick() == 0
    assert rec.calls == []


def test_default_tolerance_is_20ms_target_19ms_late_is_still_scheduled() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock)

    assert sch.schedule(T0 - 0.019, T0 - 0.019, 1, "p") == "scheduled"
    assert sch.stats()["missed_items"] == 0


def test_missed_boundary_is_strict_greater_than_window_end_plus_tolerance() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock, tolerance_s=0.25)

    # ровно now == window_end + tolerance -> НЕ missed (условие строго «>»)
    assert sch.schedule(T0 - 0.25, T0 - 0.25, 1, "edge") == "scheduled"
    # чуть дальше -> missed
    assert sch.schedule(T0 - 0.26, T0 - 0.26, 1, "over") == "missed"


def test_missed_uses_window_end_not_fire_at() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock, tolerance_s=0.25)

    # fire_at давно позади, но окно ещё открыто (window_end в будущем) -> scheduled
    assert sch.schedule(T0 - 5.0, T0 + 1.0, 1, "wide") == "scheduled"
    # fire_at в будущем, но окно уже закрыто -> missed
    assert sch.schedule(T0 + 1.0, T0 - 5.0, 1, "closed") == "missed"


def test_missed_items_sum_the_count_not_the_records() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock)

    assert sch.schedule(T0 - 5.0, T0 - 5.0, 1078, "gap") == "missed"
    assert sch.schedule(T0 - 5.0, T0 - 5.0, 3, "gap2") == "missed"

    assert sch.stats()["missed_items"] == 1081
    assert sch.pending() == 0


def test_tolerance_is_read_from_the_constructor() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock, tolerance_s=0.5)

    # 0.3 с назад: при дефолте 0.020 был бы missed, при 0.5 — scheduled
    assert sch.schedule(T0 - 0.3, T0 - 0.3, 1, "p") == "scheduled"


# --- late_fires ----------------------------------------------------------------------------------


def test_on_time_target_fired_after_tolerance_counts_one_late_fire_but_still_fires() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock, tolerance_s=0.25)
    fire_at = T0 + 0.5
    assert sch.schedule(fire_at, fire_at, 1, "p") == "scheduled"

    clock.now = fire_at + 0.28125  # 0.28125 > 0.25, двоично-точно
    assert sch.tick() == 1

    assert len(rec.calls) == 1
    assert sch.stats()["late_fires"] == 1
    assert sch.stats()["fired_items"] == 1


def test_late_boundary_is_strict_exactly_tolerance_late_is_not_a_late_fire() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock, tolerance_s=0.25)
    fire_at = T0 + 0.5
    sch.schedule(fire_at, fire_at, 1, "p")

    clock.now = fire_at + 0.25  # now - fire_at == tolerance -> не late (условие строго «>»)
    sch.tick()

    assert sch.stats()["late_fires"] == 0


def test_tick_within_tolerance_is_not_late() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock)  # tolerance 0.020
    fire_at = T0 + 0.1
    sch.schedule(fire_at, fire_at, 1, "p")

    clock.now = fire_at + 0.010
    sch.tick()

    assert sch.stats()["late_fires"] == 0


def test_late_fires_count_entries_not_items() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock, tolerance_s=0.25)
    sch.schedule(T0 + 0.5, T0 + 0.5, 1078, "gap")

    clock.now = T0 + 5.0
    assert sch.tick() == 1

    assert sch.stats()["late_fires"] == 1  # одна запись, а не 1078 кадров
    assert sch.stats()["fired_items"] == 1078


# --- count ---------------------------------------------------------------------------------------


def test_fire_receives_payload_and_the_count_of_the_entry() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)
    sch.schedule(T0 + 0.1, T0 + 0.1, 1078, {"k": "gap"})

    clock.now = T0 + 0.1
    sch.tick()

    assert [(p, c) for p, c, _ in rec.calls] == [({"k": "gap"}, 1078)]


def test_fired_items_sum_the_count_of_all_fired_entries() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock)
    sch.schedule(T0 + 0.1, T0 + 0.1, 1, "a")
    sch.schedule(T0 + 0.1, T0 + 0.1, 40, "b")
    sch.schedule(T0 + 9.0, T0 + 9.0, 7, "future")

    clock.now = T0 + 0.1
    sch.tick()

    assert sch.stats()["fired_items"] == 41  # 1 + 40, будущая запись не считается


# --- pending / stats -----------------------------------------------------------------------------


def test_pending_grows_per_schedule_and_drops_after_tick() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock)
    assert sch.pending() == 0

    sch.schedule(T0 + 0.1, T0 + 0.1, 1, "a")
    sch.schedule(T0 + 0.2, T0 + 0.2, 1, "b")
    sch.schedule(T0 + 0.3, T0 + 0.3, 1, "c")
    assert sch.pending() == 3

    clock.now = T0 + 0.2
    assert sch.tick() == 2
    assert sch.pending() == 1


def test_stats_has_the_four_named_counters_all_zero_at_start() -> None:
    sch = _make(Recorder(), FakeClock(T0))

    stats = sch.stats()

    assert {"fired_items", "missed_items", "late_fires", "unfired_on_stop_items"} <= set(stats)
    assert (stats["fired_items"], stats["missed_items"], stats["late_fires"], stats["unfired_on_stop_items"]) == (
        0,
        0,
        0,
        0,
    )


def test_stats_returns_a_snapshot_not_a_live_view() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock)
    snap = sch.stats()

    sch.schedule(T0 - 5.0, T0 - 5.0, 1, "p")  # missed

    assert snap["missed_items"] == 0
    assert sch.stats()["missed_items"] == 1


# --- Блокировки и потоки -------------------------------------------------------------------------


def test_slow_fire_does_not_block_schedule_from_another_thread() -> None:
    """``fire`` вызывается ВНЕ Condition: медленный привод не держит ``schedule()`` исполнителя."""
    clock = FakeClock(T0)
    entered = threading.Event()
    release = threading.Event()

    def slow_fire(payload: Any, count: int) -> None:
        entered.set()
        release.wait(5.0)

    sch = _make(slow_fire, clock)
    sch.schedule(T0, T0, 1, "slow")

    ticker = threading.Thread(target=sch.tick, daemon=True)
    ticker.start()
    try:
        assert entered.wait(2.0), "fire не был вызван"
        # tick() сидит внутри fire. schedule() из ДРУГОГО потока обязан вернуться.
        result = _bounded(lambda: sch.schedule(T0 + 1.0, T0 + 1.0, 1, "next"), timeout=1.0)
        assert result == "scheduled"
        assert sch.pending() == 1
    finally:
        release.set()
        ticker.join(2.0)


def test_concurrent_schedule_from_four_threads_loses_no_entry() -> None:
    clock = FakeClock(T0)
    sch = _make(Recorder(clock), clock)

    def worker() -> None:
        for _ in range(250):
            sch.schedule(T0 + 1.0, T0 + 1.0, 1, "p")

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5.0)
        assert not t.is_alive()

    assert sch.pending() == 1000


# --- run_loop ------------------------------------------------------------------------------------


def _start_loop(sch: Any) -> tuple[threading.Thread, threading.Event, threading.Event]:
    stop, pause = threading.Event(), threading.Event()
    t = threading.Thread(target=sch.run_loop, args=(stop, pause), daemon=True)
    t.start()
    return t, stop, pause


def test_stop_with_three_pending_does_not_fire_counts_them_and_exits_within_100ms() -> None:
    clock = FakeClock(T0)  # часы стоят: ни одна цель не наступит
    rec = Recorder(clock)
    sch = _make(rec, clock)
    for name in ("a", "b", "c"):
        assert sch.schedule(T0 + 100.0, T0 + 100.0, 1, name) == "scheduled"
    assert sch.pending() == 3

    t, stop, _ = _start_loop(sch)
    time.sleep(0.15)  # дать циклу уйти в ожидание ближайшего fire_at (через 100 с)
    t0 = time.perf_counter()
    stop.set()
    t.join(2.0)
    elapsed = time.perf_counter() - t0

    assert not t.is_alive(), "run_loop не вышел после stop_event.set()"
    assert elapsed <= 0.1, f"run_loop вышел за {elapsed * 1000:.0f} мс (ожидалось <= 100)"
    assert rec.calls == []
    assert sch.stats()["unfired_on_stop_items"] == 3
    assert sch.pending() == 0


def test_unfired_on_stop_sums_the_count_of_the_discarded_entries() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)
    sch.schedule(T0 + 100.0, T0 + 100.0, 2, "a")
    sch.schedule(T0 + 100.0, T0 + 100.0, 3, "b")
    sch.schedule(T0 + 100.0, T0 + 100.0, 5, "c")

    t, stop, _ = _start_loop(sch)
    time.sleep(0.1)
    stop.set()
    t.join(2.0)

    assert not t.is_alive()
    assert rec.calls == []
    assert sch.stats()["unfired_on_stop_items"] == 10
    assert sch.stats()["fired_items"] == 0


def test_run_loop_fires_a_due_entry_by_itself_when_the_clock_reaches_it() -> None:
    clock = FakeClock(T0)
    rec = Recorder(clock)
    sch = _make(rec, clock)
    sch.schedule(T0 + 1.0, T0 + 1.0, 1, "p")

    t, stop, _ = _start_loop(sch)
    try:
        time.sleep(0.15)
        assert rec.calls == [], "выстрел до наступления fire_at"
        clock.now = T0 + 1.0  # часы дошли; цикл обязан заметить за шаг <= 0.05 с
        deadline = time.perf_counter() + 2.0
        while not rec.calls and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert [(p, c) for p, c, _ in rec.calls] == [("p", 1)]
    finally:
        stop.set()
        t.join(2.0)
    assert not t.is_alive()


def test_run_loop_with_default_clock_wakes_on_schedule_and_fires_within_half_a_second() -> None:
    """Часы по умолчанию — шкала ``time.time()`` (та же, что ``capture_ts``)."""
    fired: list = []
    sch = _make(lambda payload, count: fired.append((payload, count)))
    t, stop, _ = _start_loop(sch)
    try:
        time.sleep(0.1)  # цикл уже ждёт пустую кучу
        now = time.time()
        assert sch.schedule(now + 0.1, now + 0.1, 1, "p") == "scheduled"
        deadline = time.perf_counter() + 0.5
        while not fired and time.perf_counter() < deadline:
            time.sleep(0.01)
        assert fired == [("p", 1)]
    finally:
        stop.set()
        t.join(2.0)
    assert not t.is_alive()
    assert sch.stats()["fired_items"] == 1
    assert sch.pending() == 0
