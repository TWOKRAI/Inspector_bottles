# -*- coding: utf-8 -*-
"""fix-A (ревью Ф1 run-state, m1 + m2) — hazard-тесты автора.

m1: graceful ``system.shutdown`` из ``running`` с шагами ``pre_stop``, исполнитель шагов отказал (``reply`` с
``system_stopping`` и ``False``) — машина всё равно уходит в ``shutting_down``, ``run_event`` снят, события стопа
взведены уже в ``shutting_down``.

m2: такт готовности, чья оценка начата ДО последнего входа в ``running``, не применяется: «такт оценил не готов ->
готовность вернулась -> START принят -> такт применён» не даёт ``fault`` сразу после START. Такт, начатый ПОСЛЕ START,
по-прежнему даёт ``fault`` (отбрасывание не глотает настоящую потерю готовности).

Значения — литералы; всё, что может зависнуть, — в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

from typing import Any

import pytest

from .test_run_commands import _reason, beat, make_readiness_pm, tick
from .test_run_stop import _DEADLINE_S, _beat, _bounded, _Rig, _wait

_FAILURE = [_reason("failure", "cam.p")]


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


class _RefusingExecutor:
    """Двойник ``pm-pre-stop``: отказ по контракту ``OrderedExecutor.submit`` — ``reply`` сразу и ``False``."""

    def __init__(self) -> None:
        self.calls = 0

    def submit(self, action: Any, key: Any, reply: Any, *, inline_if_idle: bool = False) -> bool:
        self.calls += 1
        reply({"success": False, "error": "system_stopping"})
        return False


# --------------------------------------------------------------------------- #
# m1: отказ исполнителя шагов при shutdown из running
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_graceful_shutdown_from_running_refused_executor_leaves_running_no_more(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True)
    rig.to_running()
    refusing = _RefusingExecutor()
    rig.pm._pre_stop_executor = refusing

    reply = _bounded(lambda: rig.pm._cmd_system_shutdown({"mode": "graceful"}), _DEADLINE_S)

    assert reply["accepted"] is True, reply
    assert refusing.calls == 1
    assert _wait(lambda: rig.pm._system_stop_event.is_set(), _DEADLINE_S), rig.log
    assert rig.state == "shutting_down"
    assert rig.pm._run_event.is_set() is False
    assert set(rig.state_at_stop_events) == {"shutting_down"}, rig.state_at_stop_events
    assert rig.pm._cmd_system_run_status()["state"] == "shutting_down"


# --------------------------------------------------------------------------- #
# m2: устаревший такт после START
# --------------------------------------------------------------------------- #


def _start_inside_tick_evaluation(pm: Any, monitor: Any) -> list[dict]:
    """Перелёт: оценка такта монитора вернула «не готов», и ДО её применения готовность вернулась и START принят.

    Оценка такта (``track_restart=True``) считается как есть; сразу после неё — свежий heartbeat «готов» и
    ``system.run.start`` (его оценка допуска видит готовность). Такт применяет СТАРЫЙ результат.
    """
    original = pm._evaluate_run_readiness
    replies: list[dict] = []

    def evaluate(**kwargs: Any) -> Any:
        result = original(**kwargs)
        if kwargs.get("track_restart") and not replies:
            beat(monitor, "cam")
            replies.append(pm._cmd_system_run_start())
        return result

    pm._evaluate_run_readiness = evaluate
    return replies


@pytest.mark.timeout(60)
def test_stale_tick_after_start_does_not_fault() -> None:
    pm, monitor = make_readiness_pm({"cam": {"class": "X"}})
    beat(monitor, "cam")
    tick(pm, monitor)
    assert pm._run_snapshot()[0].value == "ready"

    beat(monitor, "cam", ready=False, reasons=_FAILURE)
    replies = _start_inside_tick_evaluation(pm, monitor)
    _bounded(lambda: tick(pm, monitor), _DEADLINE_S)

    assert replies == [{"success": True, "state": "running"}]
    assert pm._run_snapshot()[0].value == "running"
    assert pm._run_event.is_set() is True
    assert pm._cmd_system_run_status()["last_fault"] is None


@pytest.mark.timeout(60)
def test_stale_tick_after_second_start_does_not_fault() -> None:
    """m2, второй цикл (Win-C): START -> STOP -> ``ready``, затем оценка такта начата ДО второго START, а START принят
    внутри неё — устаревший такт отброшен и после повторного входа в ``running``, не только после первого."""
    pm, monitor = make_readiness_pm({"cam": {"class": "X"}})
    beat(monitor, "cam")
    tick(pm, monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}

    assert _bounded(pm._cmd_system_run_stop, _DEADLINE_S) == {"success": True, "accepted": True, "state": "stopping"}
    # Ребёнок встал на паузу по снятому событию: последовательность STOP дожидается ``paused`` и ставит итог.
    _beat(monitor, "cam", ready=True, reasons=[], paused=True, age_s=0.0)
    assert _wait(lambda: pm._run_snapshot()[0].value != "stopping", _DEADLINE_S)
    assert pm._run_snapshot()[0].value == "ready"

    beat(monitor, "cam", ready=False, reasons=_FAILURE)
    replies = _start_inside_tick_evaluation(pm, monitor)
    _bounded(lambda: tick(pm, monitor), _DEADLINE_S)

    assert replies == [{"success": True, "state": "running"}]
    assert pm._run_snapshot()[0].value == "running"
    assert pm._run_event.is_set() is True
    assert pm._cmd_system_run_status()["last_fault"] is None


@pytest.mark.timeout(60)
def test_tick_started_after_start_still_faults() -> None:
    """Обратная сторона m2: такт, оценка которого начата после входа в ``running``, применяется — ``fault``."""
    pm, monitor = make_readiness_pm({"cam": {"class": "X"}})
    beat(monitor, "cam")
    tick(pm, monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}

    beat(monitor, "cam", ready=False, reasons=_FAILURE)
    _bounded(lambda: tick(pm, monitor), _DEADLINE_S)

    assert pm._run_snapshot()[0].value == "fault"
    assert pm._run_event.is_set() is False
