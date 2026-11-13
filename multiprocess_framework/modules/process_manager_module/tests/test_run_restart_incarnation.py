# -*- coding: utf-8 -*-
"""Task 1.7c (system-run-state) — слепые приёмочные тесты: лист readiness «воплощения, которое убьёт рестарт».

Дефект (наблюдаемое): супервизор решил перезапустить «неотвечающий» процесс (``unresponsive``) и исполняет рестарт
через backoff; пока рестарт запланирован, оживший старый процесс шлёт свежий лист, PM допускает ``system.run.ack``
(-> ``ready``) и ``system.run.start`` (-> ``running``), а после исполнения рестарта лист снят, процесс жив ->
``fault`` «нет отчёта о готовности».

Контракт (из брифа; interface.py нет): с момента РЕШЕНИЯ супервизора (или ручного ``process.restart``) до первого
heartbeat НОВОГО воплощения (``pid`` heartbeat == ``pid`` процесса в реестре после исполнения рестарта) процесс
«перезапускается»: ack -> ``not_ready``, START отказан, причина ``failure``/``liveness`` с текстом «перезапускается» и
именем процесса; лист старого воплощения (в т.ч. поздний heartbeat старого pid после исполнения рестарта) состояние
не снимает; событие супервизора ``recovered`` приходит только по heartbeat нового воплощения. В ``running``:
процесс без ``run_auto_restart`` -> ``fault`` сразу; с флагом -> ``running`` и ``out_of_spec`` «перезапуск <процесс>».
Heartbeat без поля ``pid`` не считается «старым воплощением» (совместимость).

Обвязка — настоящие объекты, как в ``test_run_commands.py`` / ``test_run_auto_restart.py``: ``make_readiness_pm``
(``ProcessManagerProcess`` + настоящий ``ProcessMonitor``), такт ``monitor._run_iteration()``. «Решение супервизора» —
настоящее: heartbeat со старой меткой времени (старше ``heartbeat_timeout`` 15 с) -> ``unresponsive`` -> монитор сам
планирует рестарт. «Исполнение рестарта» монитора — настоящий диспатч (``process.restart`` уходит в
``pm.communication.send_message``) + подмена процесса реестра на новое воплощение с другим ``pid`` (так же, как в
repro: двойник реестра сам рестарт не исполняет). Ручной рестарт — настоящий ``pm._cmd_process_restart``.

Решения тестера (ASSUMPTION; список — в отчёте):
  * ``pid`` старого и нового воплощения задаются явно (``MockProcess.start`` ставит ``hash(name) % 10000``, это
    одинаковый pid у обоих воплощений и тест бы ничего не различал);
  * после решения супервизора монитору нужен ещё один такт, чтобы PM увидел решение (в такте PM идёт ПЕРВЫМ);
    START проверяется и без такта — он оценивает внутри команды;
  * текст причин проверяется подстрокой («перезапускается» и имя процесса) — точный текст закреплён только в
    ``test_run_state_restarting.py`` (чистая ``evaluate``);
  * ``system.run.ack`` берётся после ожидания ``ack_allowed`` (до 5 с, как в repro); таймаут ожидания сам не
    ошибка — проверяется итог ack;
  * событие ``recovered`` считается по вызовам ``monitor._emit_supervisor_event(name, "recovered", ...)``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from .conftest import MockProcess
from .test_run_commands import _failure_nodes, make_readiness_pm

_OLD_PID = 41001
_NEW_PID = 41002
_BACKOFF_S = 0.3  # планируемый рестарт исполняется на такте после этой паузы
_NEVER_S = 600.0  # backoff, который в рамках теста не истекает: рестарт запланирован, но не исполнен
_STALE_HB_S = 16.0  # возраст метки времени heartbeat: больше heartbeat_timeout (15 с) -> unresponsive
_ACK_WAIT_S = 5.0
_DEADLINE_S = 60


class _NewIncarnation(MockProcess):
    """Новое воплощение: после ``start()`` pid другой (``MockProcess.start`` дал бы тот же ``hash(name)``)."""

    def start(self) -> None:
        super().start()
        self.pid = _NEW_PID


def _pm(restart_policy: dict | None = None, *, backoff: float = _NEVER_S) -> tuple[Any, Any]:
    """PM + монитор, ``cam`` с pid ``_OLD_PID`` и политикой ``enabled`` + ``backoff``; рестарт даёт ``_NEW_PID``."""
    policy = {"enabled": True, "backoff_sec": backoff, **(restart_policy or {})}
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam", "restart_policy": policy}})
    registry = pm._process_registry
    registry.get_process_by_name("cam").pid = _OLD_PID
    registry._next_process_factory["cam"] = _NewIncarnation("cam", alive=False)
    return pm, monitor


def _raw_tick(monitor: Any) -> None:
    with monitor._iteration_lock:
        monitor._run_iteration()


def _beat(
    monitor: Any, *, pid: int | None = _OLD_PID, ts_age: float = 0.0, at_age: float = 0.0, paused: bool = False
) -> float:
    """Heartbeat ``cam``: метка времени сообщения = сейчас - ``ts_age``; лист ``at`` = сейчас - ``at_age``.

    ``pid`` ``None`` — поля в сообщении нет. Возвращает ``at`` листа (для сравнения «лист не освежён»).
    """
    now = time.time()
    msg: dict[str, Any] = {
        "sender": "cam",
        "timestamp": now - ts_age,
        "status": "paused" if paused else "running",
        "readiness": {"ready": True, "reasons": [], "paused": paused, "at": now - at_age},
    }
    if pid is not None:
        msg["pid"] = pid
    monitor._on_heartbeat_received(msg)
    return now - at_age


def _spy_events(monitor: Any) -> list[tuple[str, str]]:
    """Журнал ``(процесс, событие)`` supervisor-событий монитора; сами события выполняются как прежде."""
    events: list[tuple[str, str]] = []
    original = monitor._emit_supervisor_event

    def spy(process_name: str, event: str, **kwargs: Any) -> None:
        events.append((process_name, event))
        original(process_name, event, **kwargs)

    monitor._emit_supervisor_event = spy
    return events


def _booted(pm: Any, monitor: Any) -> None:
    """Здоровый ``cam`` отчитался -> такт -> ``ready``."""
    _beat(monitor)
    _raw_tick(monitor)
    assert pm._run_state == "ready"


def _decided(pm: Any, monitor: Any) -> None:
    """Решение супервизора: метка heartbeat устарела при свежем листе -> такт -> ``unresponsive`` -> рестарт в плане."""
    _beat(monitor, ts_age=_STALE_HB_S)
    _raw_tick(monitor)
    assert monitor.get_supervision_snapshot()["cam"]["restart_count"] == 1, "предусловие: супервизор не принял решение"
    _raw_tick(monitor)  # такт PM после решения


def _executed(pm: Any, monitor: Any) -> None:
    """Исполнение рестарта: backoff истёк -> такт шлёт ``process.restart`` -> реестр держит НОВОЕ воплощение."""
    time.sleep(_BACKOFF_S + 0.15)
    _raw_tick(monitor)
    sent = [c.args[1].get("command") for c in pm.communication.send_message.call_args_list]
    assert sent == ["process.restart"], f"предусловие: рестарт не отправлен: {sent}"
    registry = pm._process_registry
    registry.remove_process("cam")
    new = registry.create_and_register("cam", "pkg.Cam", {})
    new.start()
    assert registry.get_process_by_name("cam").pid == _NEW_PID


def _restarting_reasons(reasons: list[dict]) -> list[dict]:
    return [
        r
        for r in reasons
        if r["severity"] == "failure"
        and r["node"] == "cam"
        and r["source"] == "liveness"
        and "перезапускается" in r["reason"]
        and "cam" in r["reason"]
    ]


def _assert_start_refused_restarting(pm: Any) -> None:
    reply = pm._cmd_system_run_start()
    assert reply["success"] is False, reply
    assert reply["error"] == "not_ready", reply
    assert len(_restarting_reasons(reply["reasons"])) == 1, reply
    assert pm._run_event.is_set() is False


def _manual_restart(pm: Any) -> None:
    reply = pm._cmd_process_restart({"process_name": "cam"})
    assert reply["success"] is True, f"предусловие: ручной рестарт не исполнен: {reply}"
    assert pm._process_registry.get_process_by_name("cam").pid == _NEW_PID


# --------------------------------------------------------------------------- #
# 1-2. Оживший старый процесс при запланированном рестарте: ack и START не допускаются
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S)
def test_ack_refused_when_revived_old_process_has_restart_pending() -> None:
    """``running`` -> заморозка (метка и лист старше 15 с) -> такт: ``fault`` + решение супервизора о рестарте
    (backoff не истёк) -> оживший старый процесс шлёт свежий лист ``paused`` -> ``system.run.ack``: состояние
    ``not_ready`` (не ``ready``), причина ``failure``/``liveness`` «перезапускается» с именем процесса."""
    pm, monitor = _pm()
    _booted(pm, monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    _beat(monitor, ts_age=15.3, at_age=15.4)  # kill -STOP: последний heartbeat и лист давние
    _raw_tick(monitor)
    assert pm._run_state == "fault", "предусловие: заморозка не уронила систему"
    assert monitor.get_supervision_snapshot()["cam"]["restart_count"] == 1, "предусловие: решения супервизора нет"

    _beat(monitor, paused=True, at_age=0.05)  # kill -CONT: старое воплощение, свежий лист
    deadline = time.monotonic() + _ACK_WAIT_S
    while not pm._cmd_system_run_status()["ack_allowed"] and time.monotonic() < deadline:
        time.sleep(0.02)
    reply = pm._cmd_system_run_ack()

    status = pm._cmd_system_run_status()
    assert reply["state"] == "not_ready", (reply, status)
    assert status["state"] == "not_ready", status
    assert len(_restarting_reasons(status["reasons"])) == 1, status


@pytest.mark.timeout(_DEADLINE_S)
def test_start_refused_when_supervisor_decided_restart_despite_fresh_leaf() -> None:
    """``ready``; супервизор решил перезапустить ``cam`` (лист при этом свежий, процесс жив) -> ``system.run.start``
    отказан ``not_ready`` с одной причиной «перезапускается» по узлу ``cam``; ``run_event`` не взведён."""
    pm, monitor = _pm()
    _booted(pm, monitor)

    _decided(pm, monitor)

    _assert_start_refused_restarting(pm)


# --------------------------------------------------------------------------- #
# 3-5. Исполнение рестарта: поздний heartbeat старого pid не снимает; heartbeat нового pid снимает
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S)
def test_late_old_pid_heartbeat_after_restart_executed_neither_refreshes_leaf_nor_recovers() -> None:
    """Рестарт исполнен (``process.restart`` отправлен, pid реестра сменился); поздний heartbeat СТАРОГО pid со
    свежим листом: START по-прежнему отказан «перезапускается», лист не освежён (снят или старее позднего
    heartbeat), событие ``recovered`` не пришло."""
    pm, monitor = _pm(backoff=_BACKOFF_S)
    _booted(pm, monitor)
    events = _spy_events(monitor)
    _decided(pm, monitor)
    _executed(pm, monitor)

    late_at = _beat(monitor, pid=_OLD_PID)
    _raw_tick(monitor)

    leaf = monitor.readiness_snapshot().get("cam")
    assert leaf is None or leaf["at"] < late_at, f"поздний heartbeat старого воплощения освежил лист: {leaf}"
    _assert_start_refused_restarting(pm)
    assert ("cam", "recovered") not in events, events


@pytest.mark.timeout(_DEADLINE_S)
def test_first_new_pid_heartbeat_lifts_restarting_and_emits_recovered_once() -> None:
    """Рестарт исполнен; до heartbeat нового pid ``recovered`` нет; первый heartbeat с ``pid`` == pid реестра и
    свежим листом -> такт -> ``ready``, START проходит, ``recovered`` для ``cam`` ровно один."""
    pm, monitor = _pm(backoff=_BACKOFF_S)
    _booted(pm, monitor)
    events = _spy_events(monitor)
    _decided(pm, monitor)
    _executed(pm, monitor)
    _raw_tick(monitor)
    assert ("cam", "recovered") not in events, events

    _beat(monitor, pid=_NEW_PID)
    _raw_tick(monitor)

    assert pm._run_state == "ready", pm._cmd_system_run_status()
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
    assert events.count(("cam", "recovered")) == 1, events


@pytest.mark.timeout(_DEADLINE_S)
def test_revived_old_process_before_restart_does_not_emit_recovered() -> None:
    """Решение принято, рестарт ещё не исполнен (backoff не истёк); оживший старый процесс шлёт свежий heartbeat
    -> такт: ``recovered`` для ``cam`` не приходит (это старое воплощение, рестарт его ещё убьёт)."""
    pm, monitor = _pm()
    _booted(pm, monitor)
    events = _spy_events(monitor)
    _decided(pm, monitor)

    _beat(monitor, pid=_OLD_PID)
    _raw_tick(monitor)

    assert ("cam", "recovered") not in events, events


# --------------------------------------------------------------------------- #
# 6-7. Ручной process.restart — то же состояние «перезапускается»
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S)
def test_manual_restart_old_pid_leaf_does_not_admit_start() -> None:
    """``ready``; ручной ``process.restart`` (реестр держит новое воплощение, pid другой); heartbeat СТАРОГО pid со
    свежим листом -> такт: START отказан ``not_ready`` с причиной «перезапускается» по ``cam``."""
    pm, monitor = _pm()
    _booted(pm, monitor)
    _manual_restart(pm)

    _beat(monitor, pid=_OLD_PID)
    _raw_tick(monitor)

    _assert_start_refused_restarting(pm)


@pytest.mark.timeout(_DEADLINE_S)
def test_manual_restart_lifted_by_new_pid_heartbeat() -> None:
    """Ручной ``process.restart``; heartbeat старого pid не снимает; первый heartbeat нового pid со свежим листом
    -> такт -> ``ready`` и START проходит."""
    pm, monitor = _pm()
    _booted(pm, monitor)
    _manual_restart(pm)
    _beat(monitor, pid=_OLD_PID)
    _raw_tick(monitor)

    _beat(monitor, pid=_NEW_PID)
    _raw_tick(monitor)

    assert pm._run_state == "ready", pm._cmd_system_run_status()
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}


# --------------------------------------------------------------------------- #
# 8. running: без флага — fault сразу; с флагом — running + «перезапуск»
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S)
@pytest.mark.parametrize("flagged", [False, True], ids=["no-flag-fault-at-once", "flag-keeps-running"])
def test_running_decision_to_restart_unflagged_fault_flagged_running(flagged: bool) -> None:
    """``running``; супервизор решил перезапустить ``cam`` (лист свежий, backoff 600 с — рестарт не исполнен).
    Без флага: ``fault`` сразу, ``failure`` по ``cam``, ``run_event`` снят. С ``run_auto_restart``: ``running``,
    ``run_event`` взведён, единственная причина ``out_of_spec``/``liveness`` «перезапуск cam»."""
    pm, monitor = _pm({"run_auto_restart": True} if flagged else None)
    _booted(pm, monitor)
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}

    _decided(pm, monitor)

    status = pm._cmd_system_run_status()
    if flagged:
        assert status["state"] == "running", status
        assert pm._run_event.is_set() is True
        assert [(r["node"], r["severity"], r["source"], r["reason"]) for r in status["reasons"]] == [
            ("cam", "out_of_spec", "liveness", "перезапуск cam")
        ], status
    else:
        assert status["state"] == "fault", status
        assert pm._run_event.is_set() is False
        assert _failure_nodes(status["reasons"]) == ["cam"], status


# --------------------------------------------------------------------------- #
# 9. Охранный (зелёный до реализации): без решения о рестарте лист принимается, pid не обязателен
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S)
@pytest.mark.parametrize("pid", [None, _OLD_PID], ids=["heartbeat-without-pid", "heartbeat-pid-equals-registry"])
def test_guard_leaf_accepted_when_not_restarting(pid: int | None) -> None:
    """Охранный: процесс не «перезапускается» -> лист принимается и при heartbeat без ``pid`` (старый ребёнок), и
    при ``pid`` == pid реестра: такт -> ``ready``, START проходит."""
    pm, monitor = _pm()

    _beat(monitor, pid=pid)
    _raw_tick(monitor)

    assert pm._run_state == "ready", pm._cmd_system_run_status()
    assert pm._cmd_system_run_start() == {"success": True, "state": "running"}
