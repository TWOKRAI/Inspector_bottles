# -*- coding: utf-8 -*-
"""Task 1.4 (system-run-state) — hazard-тесты автора: гонки, сбои, замки, ветки shutdown и ``run_gate: false``.

Обвязка — из слепого ``test_run_stop.py`` (``_Rig``: настоящие ``ProcessManagerProcess`` и ``ProcessMonitor``, двойник
детей ``_ChildSim``). Значения — литералы; всё, что может зависнуть, — в daemon-потоке с join-дедлайном.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from ..process.pre_stop import PreStopStep
from .test_run_commands import _reason
from .test_run_stop import _DEADLINE_S, _STOP_REPLY, _bounded, _fault_stop_done, _Rig, _unconfirmed, _wait


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


def _reasons(rig: _Rig) -> list[dict]:
    return rig.status()["reasons"]


# --------------------------------------------------------------------------- #
# Повторный STOP, гонка STOP и tick
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_repeated_stop_during_stopping_is_noop_and_tick_keeps_event(rig_factory) -> None:
    """Шаг держится (``stopping``): повторные STOP — no-op ``accepted: False``, такты не снимают событие, шаг один."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True, hold_step=True)
    rig.to_running()
    assert rig.stop() == _STOP_REPLY
    assert _wait(lambda: "step:robot.home" in rig.log, 3.0), rig.log

    for _ in range(3):
        assert rig.stop() == {"success": True, "accepted": False, "state": "stopping"}
        rig.tick()
    assert rig.state == "stopping"
    assert "clear" not in rig.log, rig.log
    assert rig.pm._run_event.is_set() is True

    rig.router.gate.set()
    assert rig.wait_not_stopping(), rig.log
    assert rig.router.requests == ["robot.home"]
    assert rig.state == "ready"


@pytest.mark.timeout(60)
def test_parallel_stops_and_ticks_exactly_one_sequence(rig_factory) -> None:
    """Восемь STOP и такты параллельно: ровно один ``accepted``, один шаг, итог ``ready``, событие снято один раз."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True, hold_step=True)
    rig.to_running()
    replies: list[dict] = []
    barrier = threading.Barrier(12)

    def stopper() -> None:
        barrier.wait(_DEADLINE_S)
        replies.append(rig.pm._cmd_system_run_stop())

    def ticker() -> None:
        barrier.wait(_DEADLINE_S)
        rig.tick()

    threads = [threading.Thread(target=stopper, daemon=True, name=f"hz-stop-{i}") for i in range(8)]
    threads += [threading.Thread(target=ticker, daemon=True, name=f"hz-tick-{i}") for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(_DEADLINE_S)
        assert not th.is_alive(), th.name
    assert sum(1 for r in replies if r.get("accepted") is True) == 1, replies
    rig.router.gate.set()
    assert rig.wait_not_stopping(), rig.log
    assert rig.router.requests == ["robot.home"]
    assert rig.log.count("clear") == 1, rig.log
    assert rig.state == "ready"


# --------------------------------------------------------------------------- #
# Сбой шага pre_stop, опоздавший ответ
# --------------------------------------------------------------------------- #


class _BoomRouter:
    """``request_async`` бросает: шаг падает исключением, STOP обязан дойти до итога."""

    def request_async(self, message: dict, on_response: Any, timeout: float = 5.0) -> str:
        raise RuntimeError("boom")


@pytest.mark.timeout(60)
def test_failed_pre_stop_step_still_reaches_paused_and_result(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True)
    rig.pm.router_manager = _BoomRouter()
    rig.to_running()

    assert rig.stop() == _STOP_REPLY

    assert rig.wait_not_stopping(), "STOP завис после упавшего шага"
    assert rig.state == "ready"
    assert rig.pm._run_event.is_set() is False
    warns = [str(c.args[0]) for c in rig.pm._log_warning.call_args_list if c.args]
    assert any("pre_stop: шаг 'cam.robot.home'" in w for w in warns), warns


@pytest.mark.timeout(60)
def test_late_step_answer_after_timeout_changes_nothing(rig_factory) -> None:
    """Шаг не ответил за 0.1 с: STOP завершается; поздний ответ — no-op (ни шага, ни события, ни состояния)."""
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True, hold_step=True)
    rig.pm._pre_stop_steps = (PreStopStep(process="cam", command="robot.home", timeout_s=0.1),)
    rig.to_running()

    assert rig.stop() == _STOP_REPLY
    assert rig.wait_not_stopping(), rig.log
    assert rig.state == "ready"
    before = list(rig.log)

    rig.router.gate.set()  # шаг отвечает с опозданием
    time.sleep(0.3)
    assert rig.log == before, rig.log
    assert rig.router.requests == ["robot.home"]
    assert rig.state == "ready"
    assert rig.pm._run_event.is_set() is False


# --------------------------------------------------------------------------- #
# Срок по умолчанию
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_default_stop_timeout_is_ten_and_bad_values_fall_back(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=None)  # ключ не задан
    assert rig.pm._run_stop_timeout() == 10.0
    rig.pm.update_config("run_stop_timeout_s", 2)
    assert rig.pm._run_stop_timeout() == 2.0
    for bad in (0, -1, True, "5", float("nan"), float("inf")):
        rig.pm.update_config("run_stop_timeout_s", bad)
        assert rig.pm._run_stop_timeout() == 10.0, bad
    warns = [
        str(c.args[0]) for c in rig.pm._log_warning.call_args_list if c.args and "run_stop_timeout_s" in str(c.args[0])
    ]
    assert len(warns) == 6, warns


# --------------------------------------------------------------------------- #
# run_gate: false — STOP и авария ничего не гейтят
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_run_gate_false_stop_skips_steps_event_and_wait(rig_factory) -> None:
    rig = rig_factory(("cam", "plc"), timeout_s=5.0, steps=True)
    rig.sim.set("plc", mode="stuck")  # paused никогда не придёт: при гейте ждали бы срок
    rig.pm._run_gate = False
    rig.pm._run_event.set()
    rig.to_running()

    t0 = time.monotonic()
    assert rig.stop() == _STOP_REPLY

    assert rig.state == "ready"  # итог сразу, без ожидания paused
    assert time.monotonic() - t0 < 2.0
    assert rig.router.requests == []
    assert rig.pm._run_event.is_set() is True
    assert "clear" not in rig.log, rig.log


@pytest.mark.timeout(60)
def test_run_gate_false_fault_marks_stop_done_at_once(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True)
    rig.pm._run_gate = False
    rig.pm._run_event.set()
    rig.to_running()
    rig.sim.set("cam", ready=False, reasons=[_reason("failure", "cam")])
    rig.sim.beat_now()

    rig.tick()

    assert rig.state == "fault"
    assert _fault_stop_done(rig.pm) is True
    assert rig.router.requests == []
    assert rig.pm._run_event.is_set() is True


# --------------------------------------------------------------------------- #
# unconfirmed_stop выходит по alive == False
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_unconfirmed_stop_leaves_set_when_process_dies(rig_factory) -> None:
    rig = rig_factory(("cam", "plc"), timeout_s=0.3)
    rig.sim.set("plc", mode="stuck")
    rig.to_running()
    assert rig.stop() == _STOP_REPLY
    assert rig.wait_not_stopping(6.0)
    assert len(_unconfirmed(_reasons(rig), "plc")) == 1

    rig.pm._process_registry._processes["plc"]._alive = False
    rig.sim.set("plc", mode="silent")
    _ready, reasons = (
        rig.pm._evaluate_run_readiness()
    )  # оценка без такта монитора: MockProcess мёртвый не отдаёт exitcode

    plc = [(r["reason"], r["source"]) for r in reasons if r.get("node") == "plc"]
    assert plc == [("процесс не жив", "liveness")], plc
    assert rig.pm._run_unconfirmed == {}


# --------------------------------------------------------------------------- #
# Ответ сразу, замки свободны во время ожидания paused
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_stop_reply_immediate_and_waiting_holds_no_locks(rig_factory) -> None:
    rig = rig_factory(("cam", "plc"), timeout_s=5.0)
    rig.sim.set("plc", mode="stuck")
    rig.to_running()

    t0 = time.monotonic()
    assert rig.stop() == _STOP_REPLY
    assert time.monotonic() - t0 < 1.0, "ответ ждал последовательность"
    assert _wait(lambda: rig.pm._run_event.is_set() is False, 3.0)

    # идёт ожидание paused у plc: ни замок держателя, ни замок монитора не заняты
    for _ in range(5):
        assert rig.pm._run_lock.acquire(timeout=1.0), "ожидание paused держит _run_lock"
        rig.pm._run_lock.release()
        assert rig.monitor._iteration_lock.acquire(timeout=1.0), "ожидание paused держит замок монитора"
        rig.monitor._iteration_lock.release()
        rig.tick()
        assert _bounded(rig.status, 1.0)["state"] == "stopping"
        time.sleep(0.05)
    assert rig.pm._cmd_system_run_start()["error"] == "stopping"


class _FakeSubmit:
    """Двойник ``_LifecycleSubmit``: запоминает поданное и не исполняет."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, Any]] = []

    def submit(self, action: Any, key: Any, reply: Any, **kwargs: Any) -> bool:
        self.calls.append((action, key, reply))
        return True


@pytest.mark.timeout(60)
def test_stop_sequence_goes_to_lifecycle_executor_with_key_none(rig_factory) -> None:
    """Документирующий: последовательность — ОДНА операция ``pm-lifecycle`` с ``key=None`` (занимает исполнитель:
    ``process.stop``/``topology.apply``/T-команды встают за ней в очередь); на потоке команды ничего не исполняется."""
    rig = rig_factory(("cam",), timeout_s=5.0)
    fake = _FakeSubmit()
    rig.pm._lifecycle_submit = fake
    rig.to_running()

    assert rig.stop() == _STOP_REPLY

    assert len(fake.calls) == 1 and fake.calls[0][1] is None, fake.calls
    assert rig.state == "stopping"  # на потоке команды итог не ставится
    _bounded(fake.calls[0][0], _DEADLINE_S)  # исполнитель берёт операцию
    assert rig.state == "ready"


# --------------------------------------------------------------------------- #
# system.shutdown: без шагов; второй graceful и STOP во время прохода
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_graceful_shutdown_from_running_without_steps_waits_paused_then_events(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0)
    rig.to_running()

    reply = _bounded(lambda: rig.pm._cmd_system_shutdown({"mode": "graceful"}), _DEADLINE_S)

    assert reply["accepted"] is True and reply["phase"] == "children", reply
    assert _wait(lambda: rig.pm._system_stop_event.is_set(), _DEADLINE_S), rig.log
    assert set(rig.state_at_stop_events) == {"shutting_down"}, rig.state_at_stop_events
    assert rig.log.index("clear") < rig.log.index("stop_events"), rig.log
    assert rig.router.requests == []


@pytest.mark.timeout(60)
def test_second_graceful_and_stop_during_shutdown_pass_do_not_start_second_pass(rig_factory) -> None:
    rig = rig_factory(("cam",), timeout_s=5.0, steps=True, hold_step=True)
    rig.to_running()
    first = _bounded(lambda: rig.pm._cmd_system_shutdown({"mode": "graceful"}), _DEADLINE_S)
    assert first["accepted"] is True and first["phase"] == "pre_stop", first
    assert _wait(lambda: "step:robot.home" in rig.log, 3.0), rig.log

    second = _bounded(lambda: rig.pm._cmd_system_shutdown({"mode": "graceful"}), _DEADLINE_S)
    assert second["accepted"] is False and second["reason"] == "already_stopping", second
    assert rig.stop() == {"success": False, "state": "running", "error": "shutting_down"}
    assert rig.pm._run_event.is_set() is True and "clear" not in rig.log, rig.log

    rig.router.gate.set()
    assert _wait(lambda: rig.pm._system_stop_event.is_set(), _DEADLINE_S), rig.log
    assert rig.router.requests == ["robot.home"]
    assert set(rig.state_at_stop_events) == {"shutting_down"}


@pytest.mark.timeout(60)
def test_wait_does_not_hang_on_dead_process_with_running_leaf(rig_factory) -> None:
    """Мёртвый процесс, чей последний лист — ``paused: false`` (был в работе): ожидание на нём не висит срок 8 с.

    Слепой тест 6 этого не отличает: его ``plc`` умирает до первого heartbeat под взведённым событием, и лист ещё
    хранит ``paused: true`` с boot (проверено мутацией «мёртвый не остановлен» — тест 6 зелёный)."""
    rig = rig_factory(("cam", "plc"), timeout_s=8.0)
    rig.to_running()
    assert _wait(lambda: rig.monitor.readiness_snapshot()["plc"]["paused"] is False, 3.0), (
        "лист plc не стал paused: false"
    )
    rig.pm._process_registry._processes["plc"]._alive = False
    rig.sim.set("plc", mode="silent")

    assert rig.stop() == _STOP_REPLY

    assert rig.wait_not_stopping(3.0), "STOP висит на мёртвом процессе (ждёт срок 8 с)"
    assert _unconfirmed(_reasons(rig), "plc") == []
