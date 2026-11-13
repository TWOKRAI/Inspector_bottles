# -*- coding: utf-8 -*-
"""Task 1.7b (system-run-state) — гистерезис допуска: ``ack``/START по листу строже, чем удержание работы.

Находка стенда: после заморозки процесса лист готовности в PM устаревает; допуск (ack/START) и удержание ``running``
судили свежесть одним порогом, и допущенная по листу возрастом ~14,9 с работа через доли секунды падала в ``fault``.
Теперь допуск — по ``2/3 stale_s`` (10 с при интервале heartbeat 5 с), удержание — по полному ``stale_s`` (15 с).

Обвязка — ``_Rig`` из ``test_run_stop.py``; листы с заданным возрастом — ручным ``_beat`` (двойник детей молчит).
Значения — литералы.
"""

from __future__ import annotations

from typing import Any

import pytest

from .test_run_commands import _reason
from .test_run_stop import _beat, _fault_stop_done, _Rig, _wait


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


def _leaf(rig: _Rig, age_s: float) -> None:
    """Двойник молчит; в мониторе — лист ``cam``: готов, на паузе, возрастом ``age_s`` с."""
    rig.sim.set("cam", mode="silent")
    _beat(rig.monitor, "cam", ready=True, reasons=[], paused=True, age_s=age_s)


def _to_acknowledgeable_fault(rig: _Rig) -> None:
    rig.to_running()
    rig.sim.set("cam", ready=False, reasons=[_reason("failure", "cam")])
    rig.sim.beat_now()
    rig.tick()
    assert rig.state == "fault"
    assert _wait(lambda: _fault_stop_done(rig.pm) is True, 5.0), "остановка в аварии не завершилась"


def _liveness(reasons: list[dict]) -> list[dict]:
    return [r for r in reasons if r.get("source") == "liveness" and r.get("reason") == "нет отчёта о готовности"]


@pytest.mark.timeout(60)
def test_admission_threshold_is_two_thirds_of_stale_and_follows_interval(rig_factory) -> None:
    rig = rig_factory(("cam",))
    assert rig.pm._run_stale_s() == 15.0
    assert rig.pm._admission_stale_s() == 10.0
    for key in ("heartbeat_interval", "heartbeat_interval_sec"):
        rig.pm.update_config(key, 2.0)
    assert rig.pm._run_stale_s() == 6.0
    assert rig.pm._admission_stale_s() == 4.0


@pytest.mark.timeout(60)
def test_ack_on_leaf_older_than_admission_goes_not_ready_with_liveness_reason(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    _to_acknowledgeable_fault(rig)
    _leaf(rig, 12.0)

    reply = rig.pm._cmd_system_run_ack()

    assert reply == {"success": True, "state": "not_ready", "error": None}, reply
    assert len(_liveness(rig.status()["reasons"])) == 1, rig.status()["reasons"]


@pytest.mark.timeout(60)
def test_ack_on_leaf_within_admission_goes_ready(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    _to_acknowledgeable_fault(rig)
    _leaf(rig, 8.0)

    assert rig.pm._cmd_system_run_ack() == {"success": True, "state": "ready", "error": None}


@pytest.mark.timeout(60)
def test_start_on_leaf_older_than_admission_refused_with_reason_fresh_leaf_runs(rig_factory) -> None:
    rig = rig_factory(("cam",))
    _leaf(rig, 12.0)

    refused = rig.pm._cmd_system_run_start()

    assert refused["success"] is False and refused["error"] == "not_ready" and refused["state"] == "not_ready", refused
    assert len(_liveness(refused["reasons"])) == 1, refused
    _beat(rig.monitor, "cam", ready=True, reasons=[], paused=True, age_s=0.5)
    rig.tick()  # свежий снимок: tick сам возвращает not_ready -> ready
    assert rig.state == "ready"
    assert rig.pm._cmd_system_run_start() == {"success": True, "state": "running"}


@pytest.mark.timeout(60)
def test_start_on_leaf_within_admission_runs(rig_factory) -> None:
    rig = rig_factory(("cam",))
    _leaf(rig, 8.0)

    assert rig.pm._cmd_system_run_start() == {"success": True, "state": "running"}


@pytest.mark.timeout(60)
def test_running_holds_on_leaf_between_admission_and_stale(rig_factory) -> None:
    """Удержание — по полному ``stale_s``: лист 12 с в ``running`` — не авария."""
    rig = rig_factory(("cam",))
    rig.to_running()
    _leaf(rig, 12.0)

    rig.tick()

    assert rig.state == "running"
    assert rig.status()["last_fault"] is None


@pytest.mark.timeout(60)
def test_running_leaf_older_than_stale_is_fault_as_before(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    rig.to_running()
    _leaf(rig, 16.0)

    rig.tick()

    assert rig.state == "fault"
    assert len(_liveness(rig.status()["last_fault"]["reasons"])) == 1
