# -*- coding: utf-8 -*-
"""Task 1.9b — юнит на счётчик отложенных T шлюза ``_TransitionGate`` (вердикт CTO по L/T, инвариант I5).

Шлюз считает T, отложенные в очередь ``pm-lifecycle``: ``+1`` под ``_routing_lock`` до подачи, ``-1`` в ``finally``
вокруг ``reply`` — после ответа, при отказе исполнителя и при исключении в действии. Сверх ``t_cap`` — отказ
``executor_busy`` из шлюза, не из исполнителя. Здесь — настоящие ``KeyedExecutor`` и ``_LifecycleSubmit``, PM — заглушка
с локом (шлюзу нужны только ``_routing_lock`` и ``_log_error``). Ожидаемые значения — литералы; ожидание — с дедлайном.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.worker_module.keyed_executor import KeyedExecutor

from ..process.process_manager_process import _LifecycleSubmit, _TransitionGate

DEADLINE_S = 5.0


class _PmStub:
    def __init__(self) -> None:
        self._routing_lock = threading.Lock()
        self.errors: list[str] = []

    def _log_error(self, message: Any, *args: Any, **kwargs: Any) -> None:
        self.errors.append(str(message))


class _Rig:
    def __init__(self, max_pending: int, t_cap: int) -> None:
        self.wm = WorkerManager("wm-gate-unit")
        self.wm.initialize()
        self.pm = _PmStub()
        self.executor = KeyedExecutor("gate-unit", worker_manager=self.wm, serial=True, max_pending=max_pending)
        self.submit = _LifecycleSubmit(self.pm, self.executor)  # type: ignore[arg-type]
        self.gate = _TransitionGate(self.pm, self.submit, t_cap=t_cap)  # type: ignore[arg-type]
        self.release = threading.Event()
        self.started = threading.Event()

    def hold_transition(self, name: str) -> threading.Event:
        """L-операция на ``name``, держащая исполнитель до ``release``; возвращает событие её ответа."""
        done = threading.Event()

        def action() -> str:
            self.started.set()
            self.release.wait(DEADLINE_S)
            return "held"

        self.submit.submit(action, frozenset({name}), lambda _result: done.set())
        assert self.started.wait(DEADLINE_S), "L-операция не стартовала"
        return done

    def close(self) -> None:
        self.release.set()
        try:
            self.executor.request_stop()
            self.executor.join_until(time.monotonic() + 2.0)
        finally:
            self.wm.shutdown()


@pytest.fixture
def make_rig():
    rigs: list[_Rig] = []

    def factory(max_pending: int = 8, t_cap: int = 2) -> _Rig:
        r = _Rig(max_pending, t_cap)
        rigs.append(r)
        return r

    yield factory
    for r in rigs:
        r.close()


def _collector() -> tuple[list[Any], threading.Event, Any]:
    results: list[Any] = []
    done = threading.Event()

    def reply(result: Any) -> None:
        results.append(result)
        done.set()

    return results, done, reply


def test_counter_returns_to_zero_after_reply(make_rig) -> None:
    """Отложенный T: пока ждёт — счётчик 1; после его ``reply`` — 0."""
    rig = make_rig()
    rig.hold_transition("a")
    results, done, reply = _collector()
    assert rig.gate.submit(lambda: "t-done", frozenset({"a"}), reply) is True
    assert rig.gate.t_pending() == 1
    rig.release.set()
    assert done.wait(DEADLINE_S), "T не ответил"
    assert results == ["t-done"]
    _wait_zero(rig)


def test_counter_returns_to_zero_after_executor_rejection(make_rig) -> None:
    """Исполнитель на своём потолке отказал T (``executor_busy`` через ``reply``) — счётчик 0, не утёк."""
    rig = make_rig(max_pending=1, t_cap=5)
    rig.hold_transition("a")
    rig.submit.submit(lambda: "filler", frozenset({"a"}), lambda _r: None)  # единственное место очереди
    results, done, reply = _collector()
    rig.gate.submit(lambda: "t-never", frozenset({"a"}), reply)
    assert done.wait(DEADLINE_S), "отказ исполнителя не дошёл до reply"
    assert results == [{"success": False, "error": "executor_busy"}]
    assert rig.gate.t_pending() == 0


def test_counter_returns_to_zero_after_exception_in_action(make_rig) -> None:
    """Исключение в действии T: исполнитель отвечает конвертом отказа, счётчик 0."""
    rig = make_rig()
    rig.hold_transition("a")

    def boom() -> None:
        raise RuntimeError("boom")

    results, done, reply = _collector()
    rig.gate.submit(boom, frozenset({"a"}), reply)
    assert rig.gate.t_pending() == 1
    rig.release.set()
    assert done.wait(DEADLINE_S), "T с исключением не ответил"
    assert results[0]["success"] is False and "boom" in results[0]["error"], results
    _wait_zero(rig)


def test_counter_returns_to_zero_when_submit_itself_raises(make_rig) -> None:
    """Сбой самой подачи (исключение из ``submit`` исполнителя): счётчик 0, исключение не проглочено."""
    rig = make_rig()
    rig.hold_transition("a")

    def broken_submit(*_args: Any, **_kwargs: Any) -> bool:
        raise RuntimeError("submit failed")

    rig.submit.submit = broken_submit  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="submit failed"):
        rig.gate.submit(lambda: None, frozenset({"a"}), lambda _r: None)
    assert rig.gate.t_pending() == 0


def test_over_t_cap_is_rejected_by_gate_and_not_counted(make_rig) -> None:
    """Сверх ``t_cap`` шлюз отвечает ``executor_busy`` сам; счётчик не растёт; действие не исполняется; после
    слива очереди принимается снова."""
    rig = make_rig(max_pending=10, t_cap=2)
    rig.hold_transition("a")
    box: list[tuple[list[Any], threading.Event]] = []
    for _ in range(2):
        results, done, reply = _collector()
        box.append((results, done))
        rig.gate.submit(lambda: "ok", frozenset({"a"}), reply)
    assert rig.gate.t_pending() == 2
    ran: list[str] = []
    rejected, rejected_done, rejected_reply = _collector()
    assert rig.gate.submit(lambda: ran.append("x"), frozenset({"a"}), rejected_reply) is False
    assert rejected == [{"success": False, "error": "executor_busy"}]
    assert rig.gate.t_pending() == 2
    rig.release.set()
    for results, done in box:
        assert done.wait(DEADLINE_S) and results == ["ok"]
    assert ran == []
    _wait_zero(rig)
    again, again_done, again_reply = _collector()
    rig.gate.submit(lambda: "later", frozenset({"a"}), again_reply)
    assert again_done.wait(DEADLINE_S) and again == ["later"]


def test_t_on_idle_target_runs_in_place_and_is_not_counted(make_rig) -> None:
    """Цель не в переходе: действие и ``reply`` на вызывающем потоке, возврат False, счётчик остаётся 0."""
    rig = make_rig()
    results, done, reply = _collector()
    assert rig.gate.submit(lambda: "inline", frozenset({"idle"}), reply) is False
    assert results == ["inline"]
    assert rig.gate.t_pending() == 0


def _wait_zero(rig: _Rig) -> None:
    """Счётчик снимается в ``finally`` после ``reply`` — на потоке исполнителя, чуть позже самого ответа."""
    end = time.monotonic() + DEADLINE_S
    while time.monotonic() < end and rig.gate.t_pending() != 0:
        time.sleep(0.005)
    assert rig.gate.t_pending() == 0
