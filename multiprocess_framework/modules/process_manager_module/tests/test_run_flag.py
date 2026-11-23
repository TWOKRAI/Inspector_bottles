# -*- coding: utf-8 -*-
"""Task 1.10 (system-run-state) — слепые приёмочные тесты ``RunFlag`` (флаг работы без межпроцессного замка).

Контракт: ``RunFlag(initial: bool = False)``; ``is_set()``, ``set()``, ``clear()``; метода ``wait`` нет
(контракт «только опрос»). Единственный писатель — процесс-родитель, читатели — дети, получившие флаг аргументом
``multiprocessing.Process`` при spawn. Главное свойство: смерть ребёнка в момент чтения не вешает родителя
(у ``multiprocessing.Event`` внутри замок; убитый в критической секции ребёнок оставляет его занятым навсегда).

Критерии (ожидания — литералы):
  1. ``RunFlag().is_set() is False``; ``RunFlag(True).is_set() is True``.
  2. ``set()`` -> True, ``clear()`` -> False, повтор идемпотентен, возвраты ``None``, ``is_set()`` — настоящий ``bool``.
  3. Родитель -> ребёнок (настоящий spawn): после ``set()`` ребёнок видит True не позже 2 с, после ``clear()`` — False.
  4. Смерть ребёнка в горячем цикле чтения не вешает ``set()/is_set()/clear()`` родителя (дедлайн 1 с);
     контроль: тот же сценарий на ``multiprocessing.Event`` (документирует, что Event подвисает).
  5. ``not hasattr(RunFlag(), "wait")``.

Каждый блокирующий вызов — в daemon-потоке с join-дедлайном; зависший ребёнок убирается в ``finally``.
Обратное направление (запись ребёнка) не тестируется: писатель один — родитель.
"""

from __future__ import annotations

import multiprocessing
import queue
import threading
import time
from typing import Any

import pytest

from ..core.run_flag import RunFlag

_CTX = multiprocessing.get_context("spawn")
_SPAWN_DEADLINE_S = 30.0  # холодный spawn с импортом пакета
_VISIBILITY_DEADLINE_S = 2.0  # критерий 3: фронт виден ребёнку не позже 2 с
_PARENT_OPS_DEADLINE_S = 1.0  # критерий 4: set/is_set/clear родителя после смерти ребёнка

# Критерий 4: задержки (с) между сигналом «ребёнок в горячем цикле» и kill(); 32 значения от 0 до 20 мс.
_KILL_DELAYS_S = [
    0.0,
    0.0005,
    0.001,
    0.0015,
    0.002,
    0.0025,
    0.003,
    0.0035,
    0.004,
    0.005,
    0.006,
    0.007,
    0.008,
    0.009,
    0.010,
    0.011,
    0.012,
    0.013,
    0.014,
    0.015,
    0.016,
    0.017,
    0.018,
    0.019,
    0.020,
    0.0003,
    0.0007,
    0.0012,
    0.0023,
    0.0047,
    0.0083,
    0.0137,
]


# --------------------------------------------------------------------------- #
# Целевые функции процессов (верхний уровень модуля — для spawn)
# --------------------------------------------------------------------------- #


def _visibility_child(flag: Any, out_q: Any) -> None:
    """Ребёнок-читатель: сообщает начальное значение, затем дожидается True, затем False (опрос, без wait)."""
    out_q.put(("started", flag.is_set()))
    end = time.monotonic() + 15.0
    while not flag.is_set() and time.monotonic() < end:
        time.sleep(0.005)
    out_q.put(("set_seen", flag.is_set()))
    while flag.is_set() and time.monotonic() < end:
        time.sleep(0.005)
    out_q.put(("clear_seen", not flag.is_set()))


def _hot_loop_child(flag: Any, in_loop: Any) -> None:
    """Ребёнок в горячем цикле чтения. ``in_loop`` — свой сигнал готовности ребёнка (не ``RunFlag``)."""
    flag.is_set()  # прогрев: первое обращение уже сделано
    in_loop.value = 1
    while True:
        flag.is_set()


# --------------------------------------------------------------------------- #
# Помощники
# --------------------------------------------------------------------------- #


def _get(out_q: Any, label: str, deadline_s: float) -> tuple[str, Any]:
    try:
        got = out_q.get(timeout=deadline_s)
    except queue.Empty:
        pytest.fail(f"ребёнок не прислал {label!r} за {deadline_s} с")
    assert got[0] == label, f"ожидали {label!r}, пришло {got!r}"
    return got


def _reap(proc: Any) -> None:
    if proc.is_alive():
        proc.kill()
    proc.join(timeout=5.0)


def _start_hot_child(flag: Any) -> tuple[Any, Any]:
    """Стартовать горячего читателя и дождаться его сигнала «в цикле»; вернуть (процесс, сигнал)."""
    in_loop = _CTX.RawValue("i", 0)
    proc = _CTX.Process(target=_hot_loop_child, args=(flag, in_loop), daemon=True)
    proc.start()
    end = time.monotonic() + _SPAWN_DEADLINE_S
    while in_loop.value == 0 and time.monotonic() < end:
        time.sleep(0.001)
    if in_loop.value == 0:
        _reap(proc)
        pytest.fail(f"ребёнок не вошёл в горячий цикл за {_SPAWN_DEADLINE_S} с (exitcode={proc.exitcode})")
    return proc, in_loop


def _parent_ops_in_daemon(flag: Any, deadline_s: float) -> tuple[bool, list[bool]]:
    """``set(); is_set(); clear(); is_set()`` в daemon-потоке с join-дедлайном.

    Возвращает ``(уложился, [is_set после set, is_set после clear])``.
    """
    seen: list[bool] = []

    def go() -> None:
        flag.set()
        seen.append(flag.is_set())
        flag.clear()
        seen.append(flag.is_set())

    th = threading.Thread(target=go, daemon=True, name="run-flag-parent-ops")
    th.start()
    th.join(deadline_s)
    return (not th.is_alive()), seen


# --------------------------------------------------------------------------- #
# Критерий 1: начальное значение
# --------------------------------------------------------------------------- #


def test_default_flag_is_clear() -> None:
    assert RunFlag().is_set() is False


def test_flag_initial_true_is_set() -> None:
    assert RunFlag(True).is_set() is True


def test_flag_initial_false_is_clear() -> None:
    assert RunFlag(False).is_set() is False


# --------------------------------------------------------------------------- #
# Критерий 2: set / clear / идемпотентность / типы
# --------------------------------------------------------------------------- #


def test_set_makes_flag_true() -> None:
    flag = RunFlag()
    flag.set()
    assert flag.is_set() is True


def test_clear_makes_flag_false() -> None:
    flag = RunFlag(True)
    flag.clear()
    assert flag.is_set() is False


def test_set_twice_is_idempotent() -> None:
    flag = RunFlag()
    flag.set()
    flag.set()
    assert flag.is_set() is True
    flag.clear()
    assert flag.is_set() is False  # одного clear хватает после двух set


def test_clear_twice_is_idempotent() -> None:
    flag = RunFlag(True)
    flag.clear()
    flag.clear()
    assert flag.is_set() is False
    flag.set()
    assert flag.is_set() is True  # одного set хватает после двух clear


def test_toggle_sequence_follows_last_write() -> None:
    flag = RunFlag()
    observed = []
    for write in (flag.set, flag.clear, flag.clear, flag.set, flag.set, flag.clear):
        write()
        observed.append(flag.is_set())
    assert observed == [True, False, False, True, True, False]


def test_set_and_clear_return_none_and_is_set_returns_real_bool() -> None:
    flag = RunFlag()
    assert flag.set() is None
    assert type(flag.is_set()) is bool
    assert flag.clear() is None
    assert type(flag.is_set()) is bool


# --------------------------------------------------------------------------- #
# Критерий 3: родитель -> ребёнок, настоящий spawn
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
def test_spawned_child_sees_parent_set_then_clear() -> None:
    """Флаг передан аргументом ``Process``; родитель переключает ПОСЛЕ спавна; ребёнок видит оба фронта за 2 с."""
    flag = RunFlag(False)
    out_q = _CTX.Queue()
    proc = _CTX.Process(target=_visibility_child, args=(flag, out_q), daemon=True)
    try:
        proc.start()
        _, initial = _get(out_q, "started", _SPAWN_DEADLINE_S)
        assert initial is False, "ребёнок при старте должен видеть снятый флаг"

        flag.set()
        _, seen_set = _get(out_q, "set_seen", _VISIBILITY_DEADLINE_S)
        assert seen_set is True, "ребёнок не увидел set() родителя"

        flag.clear()
        _, seen_clear = _get(out_q, "clear_seen", _VISIBILITY_DEADLINE_S)
        assert seen_clear is True, "ребёнок не увидел clear() родителя"
    finally:
        _reap(proc)


@pytest.mark.timeout(90)
def test_spawned_child_sees_initial_true() -> None:
    """``RunFlag(True)`` взведён к моменту спавна — ребёнок читает True сразу."""
    flag = RunFlag(True)
    out_q = _CTX.Queue()
    proc = _CTX.Process(target=_visibility_child, args=(flag, out_q), daemon=True)
    try:
        proc.start()
        _, initial = _get(out_q, "started", _SPAWN_DEADLINE_S)
        assert initial is True, "ребёнок не увидел начальное значение True"
    finally:
        _reap(proc)


# --------------------------------------------------------------------------- #
# Критерий 4: смерть ребёнка в горячем цикле не вешает родителя
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(90)
@pytest.mark.parametrize("kill_delay_s", _KILL_DELAYS_S)
def test_parent_not_hung_after_child_killed_in_hot_read_loop(kill_delay_s: float) -> None:
    flag = RunFlag(False)
    proc, _ = _start_hot_child(flag)
    try:
        time.sleep(kill_delay_s)  # отсчёт ОТ сигнала «в цикле»
        proc.kill()
        proc.join(timeout=5.0)
        assert not proc.is_alive(), "ребёнок не убит"

        finished, seen = _parent_ops_in_daemon(flag, _PARENT_OPS_DEADLINE_S)
        assert finished, (
            f"set()/is_set()/clear() родителя зависли дольше {_PARENT_OPS_DEADLINE_S} с после kill() ребёнка "
            f"(задержка kill {kill_delay_s} с): замок флага остался занятым убитым читателем"
        )
        assert seen == [True, False], f"set() -> is_set() и clear() -> is_set() дали {seen}, ожидали [True, False]"
    finally:
        _reap(proc)


@pytest.mark.timeout(240)
def test_control_multiprocessing_event_hangs_when_child_killed_in_hot_read_loop() -> None:
    """Контроль (документация): на ``multiprocessing.Event`` тот же сценарий подвисает.

    Подвисание поймано — утверждения не нужны (тест зелёный). Не поймано ни в одном прогоне — ``skip``.
    Зависшие daemon-потоки остаются в процессе pytest (замок убитого ребёнка не освободится), но прогон не вешают.
    """
    caught = 0
    for kill_delay_s in _KILL_DELAYS_S:
        event = _CTX.Event()
        proc, _ = _start_hot_child(event)
        try:
            time.sleep(kill_delay_s)
            proc.kill()
            proc.join(timeout=5.0)
            finished, _seen = _parent_ops_in_daemon(event, _PARENT_OPS_DEADLINE_S)
            if not finished:
                caught += 1
                break
        finally:
            _reap(proc)
    if not caught:
        pytest.skip("не воспроизвелось")


# --------------------------------------------------------------------------- #
# Критерий 5: контракт «только опрос»
# --------------------------------------------------------------------------- #


def test_flag_has_no_wait_method() -> None:
    assert not hasattr(RunFlag(), "wait")
