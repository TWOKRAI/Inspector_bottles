# -*- coding: utf-8 -*-
"""fix-Q1 (итоговая проверка teamlead, run-state Ф1) — hazard-тесты: поток последовательности не стартовал.

``_submit_run_sequence`` без исполнителя отдаёт последовательность одноразовому daemon-потоку. Если ``Thread.start``
бросил (``RuntimeError: can't start new thread``), итог обязан случиться всё равно — и для STOP (``run-stop``), и для
аварии (``run-fault-stop``): иначе авария остаётся в ``fault`` с ``fault_stop_done: False``, а ``system.run.ack``
отвечает ``fault_stopping`` до ``system.shutdown``.

Обвязка — ``_Rig`` из ``test_run_stop.py`` (настоящие PM и монитор, двойник детей). Подмена ``Thread.start`` — только
для потока с заданным именем. Значения — литералы; ожидание — с дедлайном.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

import pytest

from .test_run_commands import _reason
from .test_run_stop import _DEADLINE_S, _STOP_REPLY, _Rig, _wait

_FAILURE = [_reason("failure", "b.p")]
_START_OK = {"success": True, "state": "running"}


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


def _monitor_tick(rig: _Rig) -> None:
    """Такт монитора без проверки журнала ошибок (сбой старта потока пишет ERROR — это ожидаемо)."""
    with rig.monitor._iteration_lock:
        rig.monitor._run_iteration()


def _failing_start_for(thread_name: str):
    """``Thread.start``, бросающий ``RuntimeError`` только для потока с именем ``thread_name``."""
    real_start = threading.Thread.start

    def start(self: threading.Thread) -> None:
        if self.name == thread_name:
            raise RuntimeError("can't start new thread")
        real_start(self)

    return patch.object(threading.Thread, "start", start)


@pytest.mark.timeout(60)
def test_fault_stop_thread_start_failure_still_finishes_and_allows_ack(rig_factory) -> None:
    """Авария соседа ``b`` из ``running``; поток ``run-fault-stop`` не стартовал: остановка в аварии всё равно
    завершена (``fault_stop_done: True``, ``ack_allowed: True``), состояние ``fault``; ``ack`` принят (``not_ready``),
    а не ``fault_stopping``; после возврата готовности — ``ready``."""
    rig = rig_factory(("a", "b"), timeout_s=5.0)
    rig.pm._lifecycle_submit = None  # без исполнителя: последовательность идёт на одноразовом потоке
    rig.to_running()

    with _failing_start_for("run-fault-stop"):
        rig.sim.set("b", ready=False, reasons=_FAILURE)
        rig.sim.beat_now()
        _monitor_tick(rig)

    done = _wait(lambda: rig.pm._fault_stop_done is True, _DEADLINE_S)
    state = rig.state
    stop_done = rig.pm._fault_stop_done
    allowed = rig.status()["ack_allowed"]
    ack = rig.pm._cmd_system_run_ack()
    print(f"Q1 state: {state} | fault_stop_done: {stop_done} | ack: {ack}")
    assert state == "fault"
    assert done and stop_done is True, f"fault_stop_done остался False: ack={ack}"
    assert allowed is True
    assert ack == {"success": True, "state": "not_ready", "error": None}  # причина аварии жива, но выход есть

    rig.sim.set("b", ready=True, reasons=[])
    rig.sim.beat_now()
    _monitor_tick(rig)
    assert rig.state == "ready"


@pytest.mark.timeout(60)
def test_stop_thread_start_failure_still_finishes(rig_factory) -> None:
    """Контроль (поведение STOP не менялось): поток ``run-stop`` не стартовал — итог сразу, ``ready``, START принят."""
    rig = rig_factory(("a", "b"), timeout_s=5.0)
    rig.pm._lifecycle_submit = None
    rig.to_running()

    with _failing_start_for("run-stop"):
        assert rig.stop() == _STOP_REPLY

    assert rig.wait_not_stopping(), f"машина осталась в stopping: {rig.log}"
    assert rig.state == "ready"
    assert rig.pm._run_event.is_set() is False
    assert rig.pm._cmd_system_run_start() == _START_OK
