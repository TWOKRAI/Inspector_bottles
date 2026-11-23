# -*- coding: utf-8 -*-
"""Task 1.7 (system-run-state) — hazard-тесты автора ``system.run.ack``: гонки, пограничные состояния, ``last_fault``.

Обвязка — ``_Rig`` / ``_ChildSim`` из слепого ``test_run_stop.py``. Значения — литералы; зависающее — в daemon-потоке
с join-дедлайном. Сквозной тест через настоящий ``CommandManager`` не написан: регистрация без ``executor`` (класс R)
проверена слепым ``test_run_ack.py`` на двойнике менеджера команд; настоящий диспатч в обвязке PM не собран.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from .test_run_commands import _reason
from .test_run_stop import _DEADLINE_S, _fault_stop_done, _Rig, _unconfirmed, _wait


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


class _Store:
    def __init__(self) -> None:
        self.writes: list[tuple[str, Any]] = []

    def handle_state_set(self, msg: dict) -> dict:
        data = msg["data"]
        self.writes.append((data["path"], data["value"]))
        return {"status": "ok", "path": data["path"], "changed": True}

    def last(self, path: str) -> Any:
        return [v for p, v in self.writes if p == path][-1]


def _to_fault(rig: _Rig, *, wait_done: bool = True) -> None:
    """Здоровая система в ``running`` -> ``cam`` теряет готовность -> такт -> ``fault`` (остановка в аварии идёт)."""
    rig.to_running()
    rig.sim.set("cam", ready=False, reasons=[_reason("failure", "cam")])
    rig.sim.beat_now()
    rig.tick()
    assert rig.state == "fault"
    if wait_done:
        assert _wait(lambda: _fault_stop_done(rig.pm) is True, 5.0), "остановка в аварии не завершилась"


def _run_threads(workers: list) -> None:
    barrier = threading.Barrier(len(workers))
    errors: list[BaseException] = []

    def wrap(fn):
        def go() -> None:
            try:
                barrier.wait(_DEADLINE_S)
                fn()
            except BaseException as exc:  # noqa: BLE001 — в поток теста
                errors.append(exc)

        return go

    threads = [threading.Thread(target=wrap(fn), daemon=True, name=f"ack-hz-{i}") for i, fn in enumerate(workers)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(_DEADLINE_S)
        assert not th.is_alive(), th.name
    assert not errors, errors


@pytest.mark.timeout(60)
def test_ack_after_stop_timeout_goes_not_ready_with_unconfirmed_reason(rig_factory) -> None:
    """Остановка в аварии закончилась по сроку (plc не подтвердил): ack идёт, итог ``not_ready``, причина видна."""
    rig = rig_factory(("cam", "plc"), timeout_s=0.3)
    rig.sim.set("plc", mode="stuck")
    _to_fault(rig)
    assert rig.status()["ack_allowed"] is True

    reply = rig.pm._cmd_system_run_ack()

    assert reply == {"success": True, "state": "not_ready", "error": None}, reply
    status = rig.status()
    assert len(_unconfirmed(status["reasons"], "plc")) == 1, status["reasons"]
    assert len(_unconfirmed(status["last_fault"]["reasons"], "plc")) == 1, status["last_fault"]
    assert isinstance(status["last_fault"]["acknowledged_at"], float)
    assert status["ack_allowed"] is False


@pytest.mark.timeout(60)
def test_ack_with_run_gate_false_allowed_at_once_and_published(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    rig.pm._run_gate = False
    rig.pm._run_event.set()
    store = _Store()
    rig.pm._state_store_manager = store
    _to_fault(rig, wait_done=False)

    assert _fault_stop_done(rig.pm) is True  # ждать нечего: остановка «завершена» сразу
    assert rig.status()["ack_allowed"] is True
    assert store.last("system.run.ack_allowed") is True, store.writes
    assert rig.pm._cmd_system_run_ack()["success"] is True


@pytest.mark.timeout(60)
def test_ack_after_shutdown_began_refused_shutting_down(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    _to_fault(rig)
    assert rig.pm._cmd_system_shutdown({"mode": "graceful"})["accepted"] is True

    reply = rig.pm._cmd_system_run_ack()

    assert reply == {"success": False, "state": "shutting_down", "error": "shutting_down"}, reply
    assert rig.status()["ack_allowed"] is False


@pytest.mark.timeout(60)
def test_ack_while_pm_stopping_refused_and_state_untouched(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    _to_fault(rig)
    rig.pm._children_stopping = True
    try:
        reply = rig.pm._cmd_system_run_ack()
    finally:
        rig.pm._children_stopping = False

    assert reply == {"success": False, "state": "fault", "error": "shutting_down"}, reply
    assert rig.state == "fault"
    assert rig.status()["last_fault"]["acknowledged_at"] is None


@pytest.mark.timeout(60)
def test_parallel_acks_exactly_one_success_rest_no_fault(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    _to_fault(rig)
    replies: list[dict] = []

    _run_threads([lambda: replies.append(rig.pm._cmd_system_run_ack())] * 8)

    assert sum(1 for r in replies if r["success"]) == 1, replies
    assert all(r["error"] == "no_fault" for r in replies if not r["success"]), replies
    assert rig.state == "not_ready"  # cam всё ещё без готовности


@pytest.mark.timeout(60)
def test_ack_and_ticks_concurrently_one_outcome(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    _to_fault(rig)
    replies: list[dict] = []

    _run_threads([lambda: replies.append(rig.pm._cmd_system_run_ack())] + [rig.tick] * 4)

    assert [r["success"] for r in replies] == [True], replies
    assert rig.state == "not_ready"
    assert isinstance(rig.status()["last_fault"]["acknowledged_at"], float)


@pytest.mark.timeout(60)
def test_last_fault_survives_refused_start_and_is_cleared_by_successful_start(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    store = _Store()
    _to_fault(rig)
    rig.pm._state_store_manager = store
    rig.pm._publish_run_state()
    assert rig.pm._cmd_system_run_start()["error"] == "fault_unacknowledged"
    assert rig.status()["last_fault"] is not None

    assert rig.pm._cmd_system_run_ack()["state"] == "not_ready"  # cam всё ещё без готовности
    assert rig.pm._cmd_system_run_start()["error"] == "not_ready"
    assert rig.status()["last_fault"]["acknowledged_at"] is not None, "отказанный START стёр last_fault"

    rig.sim.set("cam", ready=True, reasons=[])
    rig.sim.beat_now()
    rig.tick()
    assert rig.state == "ready"
    assert rig.status()["last_fault"] is not None, "такт стёр last_fault"
    assert rig.pm._cmd_system_run_start() == {"success": True, "state": "running"}

    assert rig.status()["last_fault"] is None
    assert store.last("system.run.last_fault") is None, "в сторе остался лист last_fault"
    assert store.last("system.run.ack_allowed") is False
