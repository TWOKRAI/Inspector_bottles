# -*- coding: utf-8 -*-
"""C-88 — авторские тесты опасностей: ожидание наблюдателя ``supervision.status`` после ``done`` (ADR-PMM-045).

H1 — статус во время стопа не отдавался: ожидания нет; H2 — статус отдан только ДО стопа: ожидания нет;
H3 — свежий наблюдатель, ожидание началось РАНЬШЕ снимка ``done``: выход сразу после события и паузы;
H4 — свежий наблюдатель исчез: стоп кончается за потолок + запас; H5 — снимок с фазой ``children`` ожидание
не отпускает; H6 — ``done`` дважды (``join_until`` + ``close``): одно ожидание, флаг берётся при любом
результате первого вызова; H7 — ожидание не выходит за остаток срока (в том числе пауза после события);
H8 — исключение внутри ожидания: ERROR в лог, ``join_until`` возвращает своё значение;
H9 — PM, собранный через ``__new__``: ``_cmd_supervision_status`` не падает;
H10 — ``force`` + ребёнок, игнорирующий сигнал: итог ``killed`` доходит до наблюдателя.

Константы (``_STATUS_*``) подменяются малыми. Всё, что может повиснуть, идёт в daemon-потоке с дедлайном join.
Ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ..core.process_registry import ProcessRegistry
from ..process import process_manager_process as pm_process
from ..process.process_manager_process import ProcessManagerProcess, _ChildrenStop
from .test_pm_responsive_during_children_stop import FakeChild

JOIN_DEADLINE_S = 10.0
EPS_S = 0.15  # запас на планировщик; часы — настоящие, потолки подобраны с большим зазором
CAP_S = 0.4  # подменённый ``_STATUS_LINGER_S``
FLUSH_S = 0.05


@pytest.fixture(autouse=True)
def small_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pm_process, "_STATUS_OBSERVER_FRESH_S", 0.25)
    monkeypatch.setattr(pm_process, "_STATUS_LINGER_S", CAP_S)
    monkeypatch.setattr(pm_process, "_STATUS_FLUSH_S", FLUSH_S)


class _Group:
    """Двойник группы реестра: ``join_until`` возвращает заданное, ``kill`` — флаг."""

    def __init__(self, join_result: bool = True) -> None:
        self.join_result = join_result
        self.killed = False

    def join_until(self, deadline: float) -> bool:
        return self.join_result

    def kill(self) -> None:
        self.killed = True

    def close(self) -> None:
        pass


def _make_pm(registry: ProcessRegistry | None = None) -> ProcessManagerProcess:
    """PM через ``__new__`` (как у 246 тестовых мест) — без атрибутов, которых ``__init__`` не ставит."""
    with patch.object(ProcessManagerProcess, "__init__", lambda self, *a, **kw: None):
        pm = ProcessManagerProcess.__new__(ProcessManagerProcess)
    pm.name = "ProcessManager"
    pm.config = {}
    pm._process_registry = registry
    pm._state_store_manager = None
    pm.stop_event = threading.Event()
    pm._system_stop_event = threading.Event()
    for log in ("_log_info", "_log_warning", "_log_error", "_log_debug"):
        setattr(pm, log, MagicMock())
    return pm


def _make_stop(pm: ProcessManagerProcess, *, join_result: bool = True) -> tuple[_ChildrenStop, _Group]:
    cs = _ChildrenStop(pm)
    group = _Group(join_result)
    cs._group = group  # фаза 1 «уже была»: ``join_until`` идёт прямо в группу
    pm._children_stop = cs
    return cs, group


def _status(pm: ProcessManagerProcess) -> dict:
    return pm._cmd_supervision_status()


def _timed(target: Any) -> tuple[Any, float]:
    """Вызов в daemon-потоке с дедлайном join; возвращает ``(результат, длительность)``."""
    box: dict[str, Any] = {}

    def run() -> None:
        t0 = time.monotonic()
        try:
            box["result"] = target()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
        box["dt"] = time.monotonic() - t0

    thread = threading.Thread(target=run, daemon=True, name="c88-call")
    thread.start()
    thread.join(JOIN_DEADLINE_S)
    assert not thread.is_alive(), f"вызов не вернулся за {JOIN_DEADLINE_S} с"
    assert "error" not in box, repr(box.get("error"))
    return box.get("result"), box["dt"]


def _begin_stop(pm: ProcessManagerProcess) -> None:
    assert pm._begin_system_stop("graceful", "event", None)


def _serve_later(pm: ProcessManagerProcess, delay_s: float) -> threading.Thread:
    def run() -> None:
        time.sleep(delay_s)
        _status(pm)

    thread = threading.Thread(target=run, daemon=True, name="c88-observer")
    thread.start()
    return thread


# --------------------------------------------------------------------------- #
# H1 / H2: нет свежего наблюдателя — нулевая цена
# --------------------------------------------------------------------------- #


def test_h1_no_status_served_during_stop_means_no_linger() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)

    result, dt = _timed(lambda: cs.join_until(time.monotonic() + 5.0))

    assert result is True
    assert dt < 0.05
    assert pm._system_stop_snapshot()["phase"] == "done"


def test_h2_status_served_only_before_the_stop_means_no_linger() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    assert _status(pm)["system_stop"] is None  # снимок ДО стопа: метку не ставит
    _begin_stop(pm)

    result, dt = _timed(lambda: cs.join_until(time.monotonic() + 5.0))

    assert result is True
    assert dt < 0.05
    assert getattr(pm, "_status_served_during_stop_at", None) is None


# --------------------------------------------------------------------------- #
# H3 / H4 / H5: свежий наблюдатель
# --------------------------------------------------------------------------- #


def test_h3_fresh_observer_linger_ends_right_after_done_snapshot_and_flush() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)
    _status(pm)  # свежий опрос на фазе ``children``
    # Снимок ``done`` отдаётся ПОЗЖЕ начала ожидания: событие ставит обработчик, а не ожидающий.
    observer = _serve_later(pm, 0.1)

    result, dt = _timed(lambda: cs.join_until(time.monotonic() + 5.0))
    observer.join(JOIN_DEADLINE_S)

    assert result is True
    assert pm._status_done_served_event.is_set()
    assert 0.1 <= dt < CAP_S, f"ожидание {dt:.3f} с: должно кончиться по событию (~0.15 с), не по потолку {CAP_S}"


def test_h4_fresh_observer_that_vanishes_stop_ends_within_cap() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)
    _status(pm)  # и больше ни одного запроса

    result, dt = _timed(lambda: cs.join_until(time.monotonic() + 5.0))

    assert result is True
    assert CAP_S - 0.05 <= dt <= CAP_S + EPS_S
    assert not pm._status_done_served_event.is_set()


def test_h5_children_phase_snapshot_does_not_release_the_linger() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)
    _status(pm)
    stop_polling = threading.Event()

    def poll_children_phase() -> None:
        while not stop_polling.is_set():
            _status(pm)  # фаза ``children``: метку освежает, событие не ставит
            time.sleep(0.02)

    poller = threading.Thread(target=poll_children_phase, daemon=True, name="c88-poller")
    poller.start()
    try:
        _, dt = _timed(lambda: cs._linger_for_status_observer(None))
    finally:
        stop_polling.set()
        poller.join(JOIN_DEADLINE_S)

    assert not pm._status_done_served_event.is_set()
    assert dt >= CAP_S - 0.05  # до потолка: ``children`` не отпускает


# --------------------------------------------------------------------------- #
# H6: один раз на экземпляр
# --------------------------------------------------------------------------- #


def test_h6_done_twice_join_until_and_close_lingers_once() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)
    _status(pm)

    _, dt_first = _timed(lambda: cs.join_until(time.monotonic() + 5.0))
    _status(pm)  # наблюдатель снова «свеж»
    _, dt_close = _timed(cs.close)

    assert dt_first >= CAP_S - 0.05
    assert dt_close < 0.05  # второго ожидания нет


def test_h6_once_flag_is_taken_even_when_first_call_returned_at_once() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)

    _, dt_first = _timed(lambda: cs.join_until(time.monotonic() + 5.0))  # метки нет: выход сразу
    _status(pm)  # потом наблюдатель появился
    _, dt_close = _timed(cs.close)

    assert dt_first < 0.05
    assert dt_close < 0.05  # флаг взят первым вызовом, хотя тот ничего не ждал


# --------------------------------------------------------------------------- #
# H7: не дольше остатка срока
# --------------------------------------------------------------------------- #


def test_h7_deadline_in_the_past_means_no_wait() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)
    _status(pm)

    _, dt = _timed(lambda: cs._linger_for_status_observer(time.monotonic() - 1.0))

    assert dt < 0.05


def test_h7_wait_is_clipped_to_the_remaining_deadline() -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)
    _status(pm)

    _, dt = _timed(lambda: cs._linger_for_status_observer(time.monotonic() + 0.1))

    assert 0.05 <= dt <= 0.1 + EPS_S  # потолок 0.4, остаток 0.1


def test_h7_flush_pause_is_clipped_to_the_remaining_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pm_process, "_STATUS_FLUSH_S", 5.0)  # пауза без обрезки висела бы 5 с
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)
    _status(pm)
    pm._status_done_served_event.set()  # снимок ``done`` уже отдан

    _, dt = _timed(lambda: cs._linger_for_status_observer(time.monotonic() + 0.1))

    assert dt <= 0.1 + EPS_S


# --------------------------------------------------------------------------- #
# H8: сбой внутри ожидания не ломает стоп
# --------------------------------------------------------------------------- #


def test_h8_exception_in_linger_is_logged_and_join_until_returns_its_value(monkeypatch: pytest.MonkeyPatch) -> None:
    pm = _make_pm()
    cs, _ = _make_stop(pm)
    _begin_stop(pm)
    _status(pm)
    monkeypatch.setattr(pm_process, "_STATUS_OBSERVER_FRESH_S", "не число")  # сравнение бросит TypeError

    result, dt = _timed(lambda: cs.join_until(time.monotonic() + 5.0))

    assert result is True
    assert dt < 0.05
    messages = [str(call.args[0]) for call in pm._log_error.call_args_list]
    assert any("supervision.status" in m for m in messages), messages


# --------------------------------------------------------------------------- #
# H9: PM из ``__new__``
# --------------------------------------------------------------------------- #


def test_h9_new_built_pm_status_handler_does_not_raise_before_and_during_stop() -> None:
    pm = _make_pm()

    before, _ = _timed(lambda: _status(pm))
    _begin_stop(pm)
    during, _ = _timed(lambda: _status(pm))

    assert before["success"] is True and before["system_stop"] is None
    assert during["success"] is True and during["system_stop"]["phase"] == "children"
    assert pm._status_done_served_event is pm._status_done_served_event  # одно событие на PM


def test_h9_children_stop_double_without_init_works_with_new_pm() -> None:
    pm = _make_pm()
    cs = _ChildrenStop.__new__(_ChildrenStop)  # без ``__init__``: атрибуты уровня класса
    cs._pm = pm
    cs._group = None

    _, dt = _timed(lambda: cs._linger_for_status_observer(None))

    assert dt < 0.05


# --------------------------------------------------------------------------- #
# H10: force + ребёнок, игнорирующий сигнал: ``killed`` доходит до наблюдателя
# --------------------------------------------------------------------------- #


def test_h10_force_child_ignoring_sigterm_killed_outcome_reaches_the_observer() -> None:
    child = FakeChild("cam", [], mode="kill")  # переживает сигнал и terminate, умирает на kill
    registry = ProcessRegistry(system_stop_event=None)
    registry.add_process(child)
    registry._stop_events[child.name] = child.stop_event
    pm = _make_pm(registry)
    pm._incarnations = {"cam": 1}  # имена в снимке берутся из монитора/воплощений; монитора здесь нет
    cs = _ChildrenStop(pm)
    group = registry.children_stop(mark_reader_gone=True)
    cs._group = group
    pm._children_stop = cs
    _begin_stop(pm)
    seen: list[tuple[str | None, str | None]] = []
    stop_polling = threading.Event()

    def observe() -> None:
        while not stop_polling.is_set():
            reply = _status(pm)
            phase = (reply["system_stop"] or {}).get("phase")
            seen.append((phase, reply["processes"]["cam"]["stop_outcome"]))
            if phase == "done":
                return
            time.sleep(0.02)

    observer = threading.Thread(target=observe, daemon=True, name="c88-observer")
    observer.start()
    remainder: dict[str, float] = {}

    def scope() -> bool:
        group.request_stop()
        cs.set_force_deadline(time.monotonic() + 0.2)
        if cs.join_until(time.monotonic() + 30.0):  # срок ``force`` режет 30 с до 0.2 с
            return True
        cs.kill()
        phase3 = time.monotonic() + 3.0
        stopped = cs.join_until(phase3)
        remainder["left"] = phase3 - time.monotonic()
        return stopped

    try:
        stopped, _ = _timed(scope)
    finally:
        stop_polling.set()
        observer.join(JOIN_DEADLINE_S)

    print(f"H10: остаток срока фазы 3 после ожидания: {remainder['left']:.3f} с, снимки: {seen[-3:]}")
    assert stopped is True
    assert ("done", "killed") in seen, seen
    assert registry.stop_outcome("cam") == "killed"
