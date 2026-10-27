# -*- coding: utf-8 -*-
"""Task 1.10 (`plans/lifecycle-stop-ownership/tasks/T1.10.md`) — слепая приёмка R1-R14: честный итог стопа
``outcome`` рядом с ``success``. Написано ДО реализации; реализация не читалась.

Контракт (Goal / DESIGN D1-D4 T1.10): ответ ``process.stop`` / ``process.restart`` и запись процесса в
``supervision.status`` (поле ``stop_outcome``) говорят, как умер ребёнок: ``exited`` / ``terminated`` /
``killed`` / ``handed_over`` / ``survived`` / ``None`` (стопа не было). Источник итога — шаг эскалации
``ChildProcessStop``, не exitcode. ``success`` значит то же, что в 1.9b.

Обвязка: настоящий PM + два настоящих spawn-ребёнка (``Rig`` / ``LifecycleChild`` из тестов 1.9b),
окно ``stop_process_timeout`` = 1,0 с (кроме R8: 8,0 с — при 1,0 с ``start_slow_stop()`` гоняется с
``terminate()``). ``slow`` — хук остановки 3,0 с (> окна), ``other`` — быстрый. Ответы сравниваются
ТОЧНЫМ словарём; ожидаемые значения — литералы из таблицы путей D4. Юниты ``ChildProcessStop`` (R3, R4, R9,
R10, R14) — на подделках процессов: ``kill()`` настоящим процессом на Windows недостижим.

R6 параметризован по дверям (прямая команда / ``process.command``): на каждую — свежий PM, чтобы рестарт шёл
у живого, давно поднявшегося ``slow``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest

from backend_ctl.driver import BackendDriver

from ..core.child_process_stop import ChildProcessStop
from .test_lifecycle_fifo_acceptance import Rig

UNIT_DEADLINE_S = 20.0  # потолок юнита: дальше «завис» = упавший ассерт


# --------------------------------------------------------------------------- #
# Обвязка
# --------------------------------------------------------------------------- #


@pytest.fixture
def rig(tmp_path: Path):
    """PM с окном стопа 1,0 с."""
    r = Rig(tmp_path, stop_timeout_s=1.0)
    try:
        r.start()
        yield r
    finally:
        r.close()


@pytest.fixture
def rig_default_window(tmp_path: Path):
    """PM с окном стопа по умолчанию (8,0 с) — для R8."""
    r = Rig(tmp_path)
    try:
        r.start()
        yield r
    finally:
        r.close()


@pytest.fixture
def rig_exit3(tmp_path: Path):
    """PM с окном 1,0 с, у ``other`` хук остановки выходит ``os._exit(3)`` (R13)."""
    r = Rig(tmp_path, stop_timeout_s=1.0, child_overrides={"other": {"stop_exit_code": 3}})
    try:
        r.start()
        yield r
    finally:
        r.close()


def _stop(rig: Rig, name: str, *, nested: bool = False) -> Any:
    """``process.stop <name>`` и ответ (``None`` по дедлайну)."""
    return rig.wait_reply(rig.send("process.stop", {"process_name": name}, nested=nested))


def _bounded(call: Callable[[], Any]) -> Any:
    """Вызов в daemon-потоке с дедлайном; исключение вызова пробрасывается."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = call()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    th = threading.Thread(target=_run, daemon=True, name="unit-call")
    th.start()
    th.join(UNIT_DEADLINE_S)
    assert not th.is_alive(), f"вызов не вернулся за {UNIT_DEADLINE_S} с"
    if "error" in box:
        raise box["error"]
    return box.get("value")


class FakeEvent:
    def __init__(self) -> None:
        self.is_set = False

    def set(self) -> None:
        self.is_set = True


class FakeProc:
    """Подделка процесса. ``dies_on`` — какой сигнал её убивает: ``"terminate"`` / ``"kill"`` / ``None``.

    ``alive`` меняет и тест: «умерла сама» между шагами эскалации.
    """

    def __init__(self, *, dies_on: str | None = None) -> None:
        self.alive = True
        self.dies_on = dies_on
        self.terminate_calls = 0
        self.kill_calls = 0

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self.dies_on == "terminate":
            self.alive = False

    def kill(self) -> None:
        self.kill_calls += 1
        if self.dies_on == "kill":
            self.alive = False


def _group(procs: dict[str, FakeProc], *, should_abort: Callable[[], bool] | None = None, marks: list | None = None):
    return ChildProcessStop(
        procs,
        {name: FakeEvent() for name in procs},
        on_confirmed_dead=(lambda name, proc: marks.append(name)) if marks is not None else None,
        terminate_grace_s=0.05,
        kill_confirm_s=0.05,
        poll_s=0.01,
        should_abort=should_abort,
    )


# --------------------------------------------------------------------------- #
# R1-R2, R5-R6, R8, R11-R13: настоящий PM
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(150)
def test_outcome_exited_for_cooperative_child(rig: Rig) -> None:
    """R1: ``process.stop other`` (хук мгновенный) -> ``outcome: "exited"``."""
    reply = _stop(rig, "other")

    assert reply is not None, "ответ process.stop не пришёл за дедлайн"
    assert reply.result == {"success": True, "process_name": "other", "outcome": "exited"}, (
        f"ответ стопа кооперативного ребёнка: {reply.result}"
    )


@pytest.mark.timeout(150)
def test_outcome_terminated_for_child_ignoring_stop_event(rig: Rig) -> None:
    """R2: ``slow`` (хук 3,0 с > окна 1,0 с) -> ``terminate()`` -> ``outcome: "terminated"``, ``success: True``."""
    reply = _stop(rig, "slow")

    assert reply is not None, "ответ process.stop не пришёл за дедлайн"
    assert reply.result == {"success": True, "process_name": "slow", "outcome": "terminated"}, (
        f"ответ стопа ребёнка, не уложившегося в окно: {reply.result}"
    )
    assert rig.slow0.is_alive() is False, "slow жив после ответа об успешном стопе"


@pytest.mark.timeout(150)
def test_outcome_killed_when_terminate_unconfirmed() -> None:
    """R3: ``request_stop() -> join_until(в прошлом) -> kill() -> join_until(now + X)``; подделка гаснет только
    от настоящего ``proc.kill()`` -> ``outcomes()["a"] == "killed"``."""
    proc = FakeProc(dies_on="kill")
    group = _group({"a": proc})

    def scenario() -> dict[str, str]:
        group.request_stop()
        assert group.join_until(time.monotonic() - 1.0) is False, "предусловие: подделка мертва уже в окне"
        group.kill()
        assert group.join_until(time.monotonic() + 0.5) is True, "предусловие: настоящий kill не подтвердил смерть"
        return group.outcomes()

    assert _bounded(scenario) == {"a": "killed"}
    assert (proc.terminate_calls, proc.kill_calls) == (1, 1), "сигналы подделке: ожидались terminate ×1 и kill ×1"


@pytest.mark.timeout(150)
def test_outcome_survived_when_kill_unconfirmed() -> None:
    """R4: та же последовательность, подделка жива и после ``proc.kill()`` -> ``outcomes()["a"] == "survived"``."""
    proc = FakeProc(dies_on=None)
    group = _group({"a": proc})

    def scenario() -> dict[str, str]:
        group.request_stop()
        assert group.join_until(time.monotonic() - 1.0) is False
        group.kill()
        assert group.join_until(time.monotonic() + 0.3) is False, "предусловие: подделка подтвердила смерть"
        return group.outcomes()

    assert _bounded(scenario) == {"a": "survived"}
    assert proc.kill_calls == 1, "предусловие: настоящий kill() не был послан"


@pytest.mark.timeout(150)
def test_supervision_status_carries_stop_outcome(rig: Rig) -> None:
    """R5: после стопа ``slow`` (R2) запись ``slow`` в ``supervision.status`` — ``alive: False`` и
    ``stop_outcome == "terminated"``; у не стопавшегося ``other`` — ключ есть и ``stop_outcome is None``."""
    stop = _stop(rig, "slow")
    assert stop is not None and stop.success is True, f"предусловие: стоп slow не удался: {stop and stop.message}"

    processes = rig.processes()

    assert processes["slow"]["alive"] is False, f"slow в supervision.status: {processes['slow']}"
    assert "stop_outcome" in processes["slow"], f"в записи slow нет ключа stop_outcome: {processes['slow']}"
    assert processes["slow"]["stop_outcome"] == "terminated"
    assert "stop_outcome" in processes["other"], f"в записи other нет ключа stop_outcome: {processes['other']}"
    assert processes["other"]["stop_outcome"] is None


@pytest.mark.timeout(150)
@pytest.mark.parametrize("nested", [False, True], ids=["direct", "process_command"])
def test_restart_reply_carries_outcome_of_stop_phase(rig: Rig, nested: bool) -> None:
    """R6: ``process.restart`` ЖИВОГО ``slow`` (не остановленного раньше) обеими дверями -> ответ с ``outcome``
    стоп-фазы (``terminated``); после — у нового инстанса ``stop_outcome is None``. Ориентир 1,83 с."""
    old_pid = rig.slow0.pid
    sent = rig.send("process.restart", {"process_name": "slow"}, nested=nested)
    reply = rig.wait_reply(sent)

    assert reply is not None, "ответ process.restart не пришёл за дедлайн"
    if nested:
        assert reply.message.get("command") == "process.command.response", f"ответ не той двери: {reply.message}"
    assert reply.result == {"success": True, "process_name": "slow", "outcome": "terminated"}, (
        f"ответ рестарта живого slow: {reply.result}"
    )

    entry = rig.processes()["slow"]
    assert entry["pid"] != old_pid, "slow не получил нового воплощения"
    assert "stop_outcome" in entry, f"в записи slow нет ключа stop_outcome: {entry}"
    assert entry["stop_outcome"] is None


@pytest.mark.timeout(60)
def test_backend_ctl_restart_verified_parser_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """R7 (СТРАЖ — зелёный до и после кода): ``BackendDriver.process_restart_verified`` решает по ``pid`` /
    ``instance_restarts`` / ``alive``; ``outcome`` в ответе рестарта и ``stop_outcome`` в записи его не меняют.
    Полный набор двойников — ``backend_ctl/tests/test_restart_verified*.py``; настоящую проверку двери даёт R6."""

    def entry(pid: int, *, restarts: int, stop_outcome: str | None) -> dict[str, Any]:
        return {
            "incarnation": 0,
            "restart_count": 0,
            "last_exit": None,
            "status": "running",
            "pid": pid,
            "alive": True,
            "started_at": 1000.0,
            "instance_restarts": restarts,
            "stop_outcome": stop_outcome,
        }

    def driver(snapshots: list[dict[str, Any]]) -> BackendDriver:
        d = BackendDriver()
        state = {"i": 0}

        def fake_send(process, command, args=None, **kw):
            if command == "supervision.status":
                snap = snapshots[min(state["i"], len(snapshots) - 1)]
                state["i"] += 1
                return {"success": True, "result": {"success": True, "epoch": 0, "processes": {"lines": snap}}}
            return {"success": True, "result": {"success": True}}

        monkeypatch.setattr(d, "send_command", fake_send)
        monkeypatch.setattr(
            d,
            "system_command",
            lambda command, timeout=None: {"success": True, "outcome": "terminated"},
        )
        return d

    replaced = driver(
        [entry(24808, restarts=0, stop_outcome="terminated"), entry(26476, restarts=1, stop_outcome=None)]
    )
    res = replaced.process_restart_verified("lines", wait=5.0)
    assert res["restarted"] is True
    assert (res["pid_before"], res["pid_after"]) == (24808, 26476)

    same = driver([entry(24808, restarts=0, stop_outcome="exited")])
    res_same = same.process_restart_verified("lines", wait=1.0)
    assert res_same["restarted"] is False, "успешный ответ с outcome при том же pid не должен давать restarted=True"
    assert res_same["pid_before"] == res_same["pid_after"] == 24808


@pytest.mark.timeout(150)
def test_outcome_handed_over_when_system_stop_interrupts(rig_default_window: Rig) -> None:
    """R8: системный стоп посреди одиночного стопа ``slow`` (окно 8,0 с): ответ — ровно
    ``{"success": False, "process_name": "slow", "outcome": "handed_over"}``, ключа ``error`` нет."""
    rig = rig_default_window
    stop = rig.start_slow_stop()
    rig.send("system.shutdown")

    reply = rig.wait_reply(stop)

    assert reply is not None, "ответ process.stop не пришёл за дедлайн после system.shutdown"
    assert reply.result == {"success": False, "process_name": "slow", "outcome": "handed_over"}, (
        f"ответ прерванного системным стопом стопа: {reply.result}"
    )


@pytest.mark.timeout(150)
def test_outcome_exited_when_child_dies_before_kill_signal() -> None:
    """R9: подделка ``dies`` не умирает в окне; ТЕСТ делает её мёртвой после возврата ``join_until(<окно>)`` и до
    ``kill()`` -> сигнал ей не доставлен -> ``exited``; соседка ``near`` получила ``terminate()`` -> ``terminated``."""
    dies = FakeProc(dies_on=None)
    near = FakeProc(dies_on="terminate")
    group = _group({"dies": dies, "near": near})

    def scenario() -> dict[str, str]:
        group.request_stop()
        assert group.join_until(time.monotonic() + 0.1) is False, "предусловие: подделки не дожили до конца окна"
        dies.alive = False  # умерла сама между окном и kill()
        group.kill()
        assert group.join_until(time.monotonic() + 0.5) is True, "предусловие: группа не подтвердила смерть"
        return group.outcomes()

    assert _bounded(scenario) == {"dies": "exited", "near": "terminated"}
    assert dies.terminate_calls == 0, "умершей до kill() подделке доставлен terminate()"
    assert dies.kill_calls == 0, "умершей до kill() подделке доставлен kill()"
    assert near.terminate_calls == 1


@pytest.mark.timeout(150)
def test_outcome_handed_over_after_terminate_sent() -> None:
    """R10: ``terminate()`` доставлен, затем ``should_abort`` истинно, подделка жива -> ``handed_over``,
    не ``survived``."""
    abort = {"on": False}
    proc = FakeProc(dies_on=None)
    group = _group({"a": proc}, should_abort=lambda: abort["on"])

    def scenario() -> dict[str, str]:
        group.request_stop()
        assert group.join_until(time.monotonic() - 1.0) is False
        group.kill()
        assert proc.terminate_calls == 1, "предусловие: terminate() не доставлен до прерывания"
        abort["on"] = True
        assert group.join_until(time.monotonic() + 0.5) is False, "предусловие: join_until не прерван"
        return group.outcomes()

    assert _bounded(scenario) == {"a": "handed_over"}
    assert proc.kill_calls == 0, "прерванный стоп не должен слать настоящий kill()"


@pytest.mark.timeout(150)
def test_outcome_none_when_nothing_was_stopped(rig: Rig) -> None:
    """R11: сразу после стопа из R2 (канал итога не пуст) — ``process.stop`` уже мёртвого ``slow`` и имени, которого
    нет -> ``outcome: None``, ``success: True``; перед вторым путём — ещё один живой стоп, чтобы канал снова
    был не пуст; ``supervision.status`` у мёртвого ``slow`` держит ``stop_outcome == "terminated"``."""
    first = _stop(rig, "slow")
    assert first is not None and first.success is True, f"предусловие: стоп slow: {first and first.message}"

    dead = _stop(rig, "slow")
    assert dead is not None, "ответ process.stop уже мёртвого slow не пришёл за дедлайн"
    assert dead.result == {"success": True, "process_name": "slow", "outcome": None}, (
        f"стоп уже мёртвого slow: {dead.result}"
    )

    other = _stop(rig, "other")
    assert other is not None and other.success is True, f"предусловие: стоп other: {other and other.message}"

    ghost = _stop(rig, "ghost")
    assert ghost is not None, "ответ process.stop имени, которого нет, не пришёл за дедлайн"
    assert ghost.result == {"success": True, "process_name": "ghost", "outcome": None}, (
        f"стоп имени, которого нет: {ghost.result}"
    )

    entry = rig.processes()["slow"]
    assert "stop_outcome" in entry, f"в записи slow нет ключа stop_outcome: {entry}"
    assert entry["stop_outcome"] == "terminated"


@pytest.mark.timeout(150)
def test_stop_outcome_reset_on_new_incarnation(rig: Rig) -> None:
    """R12: после рестарта ``slow`` (R6) его запись в ``supervision.status`` — ``alive: True`` и
    ``stop_outcome is None`` (итог прошлого воплощения сброшен)."""
    restart = rig.wait_reply(rig.send("process.restart", {"process_name": "slow"}))
    assert restart is not None and restart.success is True, f"предусловие: рестарт slow: {restart and restart.message}"

    entry = rig.processes()["slow"]

    assert entry["alive"] is True, f"новое воплощение slow не живо: {entry}"
    assert "stop_outcome" in entry, f"в записи slow нет ключа stop_outcome: {entry}"
    assert entry["stop_outcome"] is None, f"итог прошлого воплощения не сброшен: {entry['stop_outcome']!r}"


@pytest.mark.timeout(150)
def test_outcome_exited_for_child_exiting_nonzero(rig_exit3: Rig) -> None:
    """R13: ``other`` на стоп-событие выходит сам ``os._exit(3)`` -> ``outcome: "exited"`` (exitcode 3 не делает
    его ``terminated`` / ``killed``)."""
    rig = rig_exit3
    other = rig.pm._process_registry.get_process_by_name("other")
    assert other is not None and other.is_alive(), "предусловие: other не поднят"

    reply = _stop(rig, "other")

    assert reply is not None, "ответ process.stop не пришёл за дедлайн"
    other.join(5.0)
    assert other.exitcode == 3, (
        f"предусловие: other вышел с кодом {other.exitcode}, ожидалось 3 (хелпер stop_exit_code)"
    )
    assert reply.result == {"success": True, "process_name": "other", "outcome": "exited"}, (
        f"ответ стопа ребёнка, вышедшего сам с кодом 3: {reply.result}"
    )


@pytest.mark.timeout(150)
def test_outcomes_observes_before_reporting() -> None:
    """R14: подделка жива до возврата последнего ``join_until(False)``, мертва к вызову ``outcomes()`` -> итог не
    ``survived`` (сигналов ей не слали -> ``exited``), ``on_confirmed_dead`` вызван ровно один раз."""
    proc = FakeProc(dies_on=None)
    marks: list[str] = []
    group = _group({"a": proc}, marks=marks)

    def scenario() -> tuple[dict[str, str], dict[str, str]]:
        group.request_stop()
        assert group.join_until(time.monotonic() - 1.0) is False, "предусловие: подделка мертва в последнем проходе"
        assert marks == [], "предусловие: метка поставлена до смерти"
        proc.alive = False  # умерла через миллисекунды после последнего прохода наблюдения
        return group.outcomes(), group.outcomes()

    first, second = _bounded(scenario)

    assert first == {"a": "exited"}
    assert second == {"a": "exited"}
    assert marks == ["a"], f"on_confirmed_dead вызван {len(marks)} раз(а), ожидалось ровно 1: {marks}"
