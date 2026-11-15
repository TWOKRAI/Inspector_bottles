# -*- coding: utf-8 -*-
"""fix-A (ревью Ф1 run-state, M1) — hazard-тесты: отказ и исключение подачи последовательности STOP и аварии.

Контракт ``OrderedExecutor.submit`` (``worker_module/interfaces.py``): отказ — ``reply({"success": False, "error":
"executor_busy" | "system_stopping"})`` и ``False`` без исключения; поставленная операция, снятая при закрытии, тоже
получает ``system_stopping`` через ``reply``. Требование: отказ и исключение подачи — один путь для STOP и аварии,
машина не остаётся в ``stopping`` и ``fault`` без итога. Итог к сроку: STOP -> ``ready``/``not_ready``; авария ->
остановка завершена, ``ack_allowed: True``.

Обвязка — ``_Rig`` из ``test_run_stop.py`` (настоящие PM и монитор, двойник детей). Подача — двойники по контракту и
настоящие ``KeyedExecutor`` + ``_LifecycleSubmit``. Значения — литералы; ожидание — с дедлайном.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from multiprocess_framework.modules.worker_module import WorkerManager
from multiprocess_framework.modules.worker_module.keyed_executor import KeyedExecutor

from ..process.process_manager_process import _LifecycleSubmit
from .test_run_commands import _reason
from .test_run_stop import _DEADLINE_S, _STOP_REPLY, _Rig, _wait

_FAILURE = [_reason("failure", "cam.p")]
_START_OK = {"success": True, "state": "running"}
_ACK_OK = {"success": True, "state": "ready", "error": None}


@pytest.fixture
def rig_factory():
    rigs: list[_Rig] = []

    def make(*args: Any, **kwargs: Any) -> _Rig:
        rig = _Rig(*args, **kwargs)
        rigs.append(rig)
        return rig

    yield make
    for rig in rigs:
        rig.close()


class _RefusingSubmit:
    """Двойник подачи: отказ по контракту — ``reply`` с ошибкой на вызывающем потоке и ``False``."""

    def __init__(self, error: str) -> None:
        self.error = error
        self.calls = 0

    def submit(self, action: Any, key: Any, reply: Any, *, inline_if_idle: bool = False) -> bool:
        self.calls += 1
        reply({"success": False, "error": self.error})
        return False

    def busy(self) -> bool:
        return False

    def in_transition(self, name: str) -> bool:
        return False


class _RaisingSubmit:
    """Двойник подачи, нарушающий контракт: исключение из ``submit``."""

    def submit(self, action: Any, key: Any, reply: Any, *, inline_if_idle: bool = False) -> bool:
        raise RuntimeError("boom")

    def busy(self) -> bool:
        return False

    def in_transition(self, name: str) -> bool:
        return False


class _RealLifecycle:
    """Настоящие ``KeyedExecutor`` (последовательный, потолок ``max_pending``) и ``_LifecycleSubmit`` у PM рига."""

    def __init__(self, rig: _Rig, max_pending: int) -> None:
        self.wm = WorkerManager("wm-fix-a-refusal")
        self.wm.initialize()
        self.executor = KeyedExecutor(
            "pm-lifecycle-fix-a",
            worker_manager=self.wm,
            serial=True,
            max_pending=max_pending,
            should_reject=rig.pm._lifecycle_rejected,
        )
        if getattr(rig.pm, "_routing_lock", None) is None:
            rig.pm._routing_lock = threading.Lock()  # замок счётчиков адаптера (в бою — из initialize)
        rig.pm._lifecycle_executor = self.executor
        rig.pm._lifecycle_submit = _LifecycleSubmit(rig.pm, self.executor)
        self.release = threading.Event()

    def hold(self) -> None:
        """Занять исполнитель операцией до ``release``; вернуться, когда она пошла."""
        started = threading.Event()

        def action() -> None:
            started.set()
            self.release.wait(_DEADLINE_S)

        assert self.executor.submit(action, frozenset({"hold"}), lambda _result: None) is True
        assert started.wait(_DEADLINE_S), "держащая операция не стартовала"

    def close(self) -> None:
        self.release.set()
        try:
            self.executor.request_stop()
            self.executor.join_until(time.monotonic() + 2.0)
        finally:
            self.wm.shutdown()


def _status(rig: _Rig) -> dict:
    return rig.pm._cmd_system_run_status()


def _monitor_tick(rig: _Rig) -> None:
    """Такт монитора без проверки журнала ошибок (исключение подачи пишет ERROR — это ожидаемо)."""
    with rig.monitor._iteration_lock:
        rig.monitor._run_iteration()


# --------------------------------------------------------------------------- #
# Отказ исполнителя по контракту
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_refused_by_executor_still_finishes(rig_factory) -> None:
    """STOP из ``running``, исполнитель отказал (``executor_busy``): последовательность всё равно идёт — шаг ровно один,
    событие снято, итог ``ready``; START снова принят."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True)
    refusing = _RefusingSubmit("executor_busy")
    rig.pm._lifecycle_submit = refusing
    rig.to_running()

    assert rig.stop() == _STOP_REPLY

    assert rig.wait_not_stopping(), f"машина осталась в stopping: {rig.log}"
    assert rig.state == "ready"
    assert rig.pm._run_event.is_set() is False
    assert rig.router.requests == ["robot.home"]
    assert refusing.calls == 1
    assert rig.pm._cmd_system_run_start() == _START_OK


@pytest.mark.timeout(60)
def test_fault_stop_refused_by_executor_allows_ack(rig_factory) -> None:
    """Авария, исполнитель отказал (``executor_busy``): остановка в аварии завершается к сроку — ``ack_allowed: True``;
    состояние ``fault``; после возврата готовности ``ack`` принят."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    rig.pm._lifecycle_submit = _RefusingSubmit("executor_busy")
    rig.to_running()

    rig.sim.set("cam", ready=False, reasons=_FAILURE)
    rig.sim.beat_now()
    rig.tick()

    assert rig.state == "fault"
    assert _wait(lambda: _status(rig)["ack_allowed"] is True, _DEADLINE_S), _status(rig)
    assert rig.state == "fault"
    assert rig.pm._run_event.is_set() is False

    rig.sim.set("cam", ready=True, reasons=[])
    rig.sim.beat_now()
    rig.tick()
    assert rig.pm._cmd_system_run_ack() == _ACK_OK


# --------------------------------------------------------------------------- #
# Исключение подачи — тот же путь
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_executor_raises_same_path_for_stop_and_fault_stop(rig_factory) -> None:
    """``submit`` бросил: STOP проходит ту же последовательность (шаг отправлен, итог ``ready``), авария доходит до
    ``ack_allowed: True`` — а не застревает в ``fault`` с отказом ``fault_stopping``."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True)
    rig.pm._lifecycle_submit = _RaisingSubmit()
    rig.to_running()

    assert rig.stop() == _STOP_REPLY
    assert rig.wait_not_stopping(), f"машина осталась в stopping: {rig.log}"
    assert rig.state == "ready"
    assert rig.router.requests == ["robot.home"]

    assert rig.pm._cmd_system_run_start() == _START_OK
    rig.sim.set("cam", ready=False, reasons=_FAILURE)
    rig.sim.beat_now()
    _monitor_tick(rig)
    assert rig.state == "fault"
    assert _wait(lambda: _status(rig)["ack_allowed"] is True, _DEADLINE_S), _status(rig)

    rig.sim.set("cam", ready=True, reasons=[])
    rig.sim.beat_now()
    _monitor_tick(rig)
    assert rig.pm._cmd_system_run_ack() == _ACK_OK
    assert rig.router.requests == ["robot.home"]  # авария шаги pre_stop пропускает


# --------------------------------------------------------------------------- #
# Настоящий исполнитель: executor_busy и system_stopping
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_executor_busy_and_system_stopping_both_handled(rig_factory) -> None:
    """Настоящий ``KeyedExecutor``: (1) очередь на потолке — STOP получает ``executor_busy`` и всё равно доходит до
    ``ready``; (2) исполнитель закрыт — авария получает ``system_stopping`` и всё равно доходит до ``ack_allowed``."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    real = _RealLifecycle(rig, max_pending=1)
    try:
        rig.to_running()
        real.hold()
        assert real.executor.submit(lambda: None, frozenset({"filler"}), lambda _result: None) is True  # потолок

        assert rig.stop() == _STOP_REPLY
        assert rig.wait_not_stopping(), f"executor_busy: машина осталась в stopping: {rig.log}"
        assert rig.state == "ready"
        assert rig.pm._run_event.is_set() is False

        real.release.set()
        assert rig.pm._cmd_system_run_start() == _START_OK
        real.executor.request_stop()  # закрыт: новые подачи — system_stopping

        rig.sim.set("cam", ready=False, reasons=_FAILURE)
        rig.sim.beat_now()
        rig.tick()
        assert rig.state == "fault"
        assert _wait(lambda: _status(rig)["ack_allowed"] is True, _DEADLINE_S), _status(rig)
        assert rig.state == "fault"
    finally:
        real.close()


@pytest.mark.timeout(60)
def test_queued_stop_dropped_on_executor_close_still_finishes(rig_factory) -> None:
    """STOP поставлен в очередь настоящего исполнителя (за держащей операцией), исполнитель закрыт — очередь получает
    ``system_stopping`` через ``reply`` (не возвратом ``submit``). Итог STOP всё равно ``ready``."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    real = _RealLifecycle(rig, max_pending=4)
    try:
        rig.to_running()
        real.hold()

        assert rig.stop() == _STOP_REPLY
        time.sleep(0.05)
        assert rig.state == "stopping"  # в очереди за держащей операцией

        real.executor.request_stop()
        assert rig.wait_not_stopping(), f"снятый STOP: машина осталась в stopping: {rig.log}"
        assert rig.state == "ready"
        assert rig.pm._run_event.is_set() is False
    finally:
        real.close()


# --------------------------------------------------------------------------- #
# Нарушения контракта: False без ответа; две причины обхода на одну подачу
# --------------------------------------------------------------------------- #


class _FalseWithoutReplySubmit:
    """Двойник подачи, нарушающий контракт: ``False`` и ``reply`` не вызван вовсе."""

    def submit(self, action: Any, key: Any, reply: Any, *, inline_if_idle: bool = False) -> bool:
        return False

    def busy(self) -> bool:
        return False

    def in_transition(self, name: str) -> bool:
        return False


class _RefuseThenRaiseSubmit:
    """Двойник подачи с двумя причинами обхода подряд: ``reply`` с отказом ``executor_busy``, затем исключение."""

    def submit(self, action: Any, key: Any, reply: Any, *, inline_if_idle: bool = False) -> bool:
        reply({"success": False, "error": "executor_busy"})
        raise RuntimeError("boom after refusal")

    def busy(self) -> bool:
        return False

    def in_transition(self, name: str) -> bool:
        return False


@pytest.mark.timeout(60)
def test_false_without_reply_still_finishes_stop_and_fault_stop(rig_factory) -> None:
    """``submit`` вернул ``False`` без ``reply``: STOP доходит до ``ready``, авария — до ``ack_allowed: True``."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    rig.pm._lifecycle_submit = _FalseWithoutReplySubmit()
    rig.to_running()

    assert rig.stop() == _STOP_REPLY
    assert rig.wait_not_stopping(), f"машина осталась в stopping: {rig.log}"
    assert rig.state == "ready"

    assert rig.pm._cmd_system_run_start() == _START_OK
    rig.sim.set("cam", ready=False, reasons=_FAILURE)
    rig.sim.beat_now()
    rig.tick()
    assert rig.state == "fault"
    assert _wait(lambda: _status(rig)["ack_allowed"] is True, _DEADLINE_S), _status(rig)


@pytest.mark.timeout(60)
def test_two_bypass_causes_run_action_exactly_once(rig_factory) -> None:
    """Отказ через ``reply`` и затем исключение из ``submit`` на ОДНУ подачу: ``action`` исполнена ровно один раз,
    ``reply`` вызван ровно один раз."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    rig.pm._lifecycle_submit = _RefuseThenRaiseSubmit()
    calls: list[int] = []
    replies: list[Any] = []
    replied = threading.Event()

    def action() -> str:
        calls.append(1)
        return "done"

    def reply(result: Any) -> None:
        replies.append(result)
        replied.set()

    rig.pm._submit_run_sequence(action, "run-test", reply)

    assert replied.wait(_DEADLINE_S), "ответ не пришёл"
    time.sleep(0.2)  # окно для второго (лишнего) прохода
    assert calls == [1]
    assert replies == ["done"]
