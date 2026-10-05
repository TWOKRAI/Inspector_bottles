# -*- coding: utf-8 -*-
"""Task 5.2 — авторские тесты ОПАСНОСТЕЙ механизма ``ActuationScheduler`` (ADR-PM-051).

Приёмку пишет слепой tester (``test_actuation_scheduler.py``). Здесь — то, что видно только
автору по устройству механизма:

* ``fire`` зовётся ВНЕ ``Condition``: значит ``schedule()`` может прийти посреди ``tick()``, и
  запись не должна ни потеряться, ни выстрелить дважды;
* исключение из ``fire`` не имеет права убить ``run_loop`` (иначе воркер ``actuation`` молча
  умирает, а цели копятся без выстрелов);
* ``fire`` может звать ``schedule()`` сам (привод ставит следующий шаг) — замок не реентерабелен
  под ``fire``, потому что ``fire`` вне него; дедлок здесь = регрессия «fire под замком»;
* ``pause_event`` паркует цикл без выстрелов, стоп из паузы считает невыстреленное;
* допуск per-entry: два плагина с разными ``actuation_tolerance_ms`` в ОДНОМ планировщике
  процесса не делят допуск.

Любой вызов, способный блокироваться, идёт в daemon-потоке с дедлайном на ``join``.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from multiprocess_framework.modules.process_module.generic.actuation_scheduler import ActuationScheduler
from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices

T0 = 100.0


class FakeClock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _bounded(fn: Callable[[], Any], timeout: float = 5.0) -> Any:
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


def _start_loop(sch: ActuationScheduler) -> tuple[threading.Thread, threading.Event, threading.Event]:
    stop, pause = threading.Event(), threading.Event()
    t = threading.Thread(target=sch.run_loop, args=(stop, pause), daemon=True)
    t.start()
    return t, stop, pause


def _wait_until(cond: Callable[[], bool], timeout: float = 2.0) -> bool:
    deadline = time.perf_counter() + timeout
    while not cond():
        if time.perf_counter() > deadline:
            return False
        time.sleep(0.005)
    return True


# --- Гонка schedule() против tick() ---------------------------------------------------------------


def test_schedule_racing_tick_loses_nothing_and_fires_each_entry_once() -> None:
    """4 писателя ставят наступившие цели, пока 2 потока жмут ``tick()``: каждая — ровно один выстрел."""
    fired: list[int] = []
    fired_lock = threading.Lock()

    def fire(payload: int, count: int) -> None:
        with fired_lock:
            fired.append(payload)

    sch = ActuationScheduler(fire, tolerance_s=10.0)
    stop_ticking = threading.Event()

    def writer(base: int) -> None:
        for i in range(500):
            now = time.time()
            assert sch.schedule(now, now, 1, base + i) == "scheduled"

    def ticker() -> None:
        while not stop_ticking.is_set():
            sch.tick()

    tickers = [threading.Thread(target=ticker, daemon=True) for _ in range(2)]
    writers = [threading.Thread(target=writer, args=(k * 1000,), daemon=True) for k in range(4)]
    for t in tickers + writers:
        t.start()
    for t in writers:
        t.join(10.0)
        assert not t.is_alive()
    stop_ticking.set()
    for t in tickers:
        t.join(5.0)
        assert not t.is_alive()
    _bounded(sch.tick)  # добрать то, что успело встать после последнего тика

    assert sch.pending() == 0
    assert len(fired) == 2000, f"выстрелов {len(fired)} из 2000"
    assert len(set(fired)) == 2000, "какая-то цель выстрелила дважды"
    assert sch.stats()["fired_items"] == 2000


# --- Исключение из fire ---------------------------------------------------------------------------


def test_fire_exception_is_counted_reported_and_does_not_stop_tick() -> None:
    clock = FakeClock()
    errors: list[BaseException] = []
    fired: list[str] = []

    def fire(payload: str, count: int) -> None:
        if payload == "bad":
            raise RuntimeError("привод отказал")
        fired.append(payload)

    sch = ActuationScheduler(fire, clock=clock, on_error=errors.append)
    sch.schedule(T0 + 0.1, T0 + 0.1, 1, "bad")
    sch.schedule(T0 + 0.2, T0 + 0.2, 1, "good")

    clock.now = T0 + 0.2
    assert _bounded(sch.tick) == 2  # tick не бросил, выстрелил обе записи

    assert fired == ["good"]  # отказ первой не отменил вторую
    assert sch.stats()["fire_errors"] == 1
    assert [str(e) for e in errors] == ["привод отказал"]


def test_fire_exception_does_not_kill_run_loop() -> None:
    clock = FakeClock()
    fired: list[str] = []

    def fire(payload: str, count: int) -> None:
        if payload == "bad":
            raise RuntimeError("привод отказал")
        fired.append(payload)

    sch = ActuationScheduler(fire, clock=clock)
    sch.schedule(T0, T0, 1, "bad")
    t, stop, _ = _start_loop(sch)
    try:
        assert _wait_until(lambda: sch.stats()["fire_errors"] == 1), "отказ fire не посчитан"
        assert t.is_alive(), "run_loop умер на исключении fire"
        sch.schedule(T0, T0, 1, "good")
        assert _wait_until(lambda: fired == ["good"]), "после отказа цикл больше не стреляет"
    finally:
        stop.set()
        t.join(2.0)
    assert not t.is_alive()


def test_broken_on_error_handler_does_not_kill_tick_either() -> None:
    clock = FakeClock()

    def fire(payload: Any, count: int) -> None:
        raise ValueError("x")

    def on_error(exc: BaseException) -> None:
        raise RuntimeError("обработчик тоже сломан")

    sch = ActuationScheduler(fire, clock=clock, on_error=on_error)
    sch.schedule(T0, T0, 1, "p")

    assert _bounded(sch.tick) == 1
    assert sch.stats()["fire_errors"] == 1


def test_context_scheduler_reports_fire_failure_through_health_not_a_crash() -> None:
    """Планировщик процесса: сломанный payload — инцидент health, tick() не бросает."""
    svc = MockProcessServices(name="hazard")
    svc.worker_manager = None  # type: ignore[assignment]
    ctx = PluginContext(svc, plugin_name="robot_control")
    sch = ctx.scheduler

    def broken_payload(count: int) -> None:
        raise RuntimeError("payload отказал")

    now = time.time()
    sch.schedule(now, now, 1, broken_payload, tolerance_s=10.0)

    assert _bounded(sch.tick) == 1
    assert sch.stats()["fire_errors"] == 1
    from multiprocess_framework.modules.process_module.health import get_or_create_health_state

    assert get_or_create_health_state(svc).error_count == 1


# --- Реентерабельный schedule() из fire -----------------------------------------------------------


def test_fire_may_call_schedule_reentrantly_without_deadlock() -> None:
    clock = FakeClock()
    holder: dict = {}

    def fire(payload: str, count: int) -> None:
        if payload == "first":
            # привод ставит следующий шаг — тот же планировщик, из-под tick()
            holder["result"] = holder["sch"].schedule(T0, T0, 1, "second")

    sch = ActuationScheduler(fire, clock=clock)
    holder["sch"] = sch
    sch.schedule(T0, T0, 1, "first")

    assert _bounded(sch.tick, timeout=2.0) == 1  # дедлок здесь = fire зовётся под замком
    assert holder["result"] == "scheduled"
    assert sch.pending() == 1  # вторая цель ждёт СЛЕДУЮЩЕГО тика, этот её не съел
    assert _bounded(sch.tick, timeout=2.0) == 1
    assert sch.pending() == 0


# --- pause_event ----------------------------------------------------------------------------------


def test_pause_parks_the_loop_without_firing_and_resume_fires() -> None:
    clock = FakeClock()
    fired: list[str] = []
    sch = ActuationScheduler(lambda p, c: fired.append(p), clock=clock)
    t, stop, pause = _start_loop(sch)
    try:
        pause.set()
        time.sleep(0.12)  # цикл увидел паузу
        sch.schedule(T0, T0, 1, "p")  # цель уже наступила
        time.sleep(0.15)
        assert fired == [], "выстрел во время паузы"
        assert sch.pending() == 1
        pause.clear()
        assert _wait_until(lambda: fired == ["p"]), "после снятия паузы цель не выстрелила"
    finally:
        stop.set()
        t.join(2.0)
    assert not t.is_alive()


def test_stop_while_paused_exits_and_counts_unfired() -> None:
    clock = FakeClock()
    sch = ActuationScheduler(lambda p, c: None, clock=clock)
    sch.schedule(T0 + 50.0, T0 + 50.0, 4, "p")
    t, stop, pause = _start_loop(sch)
    pause.set()
    time.sleep(0.1)
    t0 = time.perf_counter()
    stop.set()
    t.join(2.0)

    assert not t.is_alive()
    assert time.perf_counter() - t0 <= 0.1
    assert sch.stats()["unfired_on_stop_items"] == 4
    assert sch.pending() == 0


# --- Допуск per-entry: два плагина в одном планировщике -------------------------------------------


def test_two_plugins_with_different_tolerances_share_one_scheduler_without_sharing_tolerance() -> None:
    clock = FakeClock()
    sch = ActuationScheduler(lambda p, c: None, clock=clock, tolerance_s=0.25)

    # окно закрылось 0.125 с назад: строгому плагину (0.0625) поздно, мягкому (0.5) — нет
    assert sch.schedule(T0 - 0.125, T0 - 0.125, 1, "strict", tolerance_s=0.0625) == "missed"
    assert sch.schedule(T0 - 0.125, T0 - 0.125, 1, "lenient", tolerance_s=0.5) == "scheduled"
    # без tolerance_s — допуск конструктора (0.25): тоже ставится
    assert sch.schedule(T0 - 0.125, T0 - 0.125, 1, "default") == "scheduled"
    assert sch.stats()["missed_items"] == 1

    # late_fires тоже по допуску записи: обе цели стреляют на 0.375 с позже fire_at
    sch2 = ActuationScheduler(lambda p, c: None, clock=clock, tolerance_s=0.25)
    sch2.schedule(T0 + 1.0, T0 + 1.0, 1, "strict", tolerance_s=0.0625)
    sch2.schedule(T0 + 1.0, T0 + 1.0, 1, "lenient", tolerance_s=0.5)
    clock.now = T0 + 1.375
    assert sch2.tick() == 2
    assert sch2.stats()["late_fires"] == 1  # опоздал только строгий
