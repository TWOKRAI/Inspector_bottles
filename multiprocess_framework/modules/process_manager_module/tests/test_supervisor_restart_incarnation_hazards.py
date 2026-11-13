# -*- coding: utf-8 -*-
"""Task 1.8b (system-run-state) — hazard-тесты автора: воплощение процесса в машине статусов супервизора.

Слепые приёмочные (``test_supervisor_restart_incarnation.py``) закрывают ACCEPTANCE 1-6; здесь — гонки, повторы,
порядок и соседи по механизму. Обвязка — та же, что у слепых (настоящие ``ProcessMonitor``, ``SharedResourcesManager``
+ ``ProcessStateRegistry``, ``PM.restart_process``; двойники — только процесс ОС и реестр OS-процессов): ``_Rig`` и
двойники берутся из слепого файла, настоящий реестр для нескольких процессов подключает ``attach_real_srm``.

  H1  новое воплощение умирает ДО первого heartbeat (пометка ``_restarting`` держит pid прежнего) -> падение, 2/3.
  H2  настоящий цикл монитора (``poll_interval`` 0,01) + стоп с задержкой: 50 повторов, у каждого ровно один рестарт.
  H3  один и тот же мёртвый объект на многих тактах -> одно событие ``crashed``.
  H4  каскад ``rest_for_one``: выход induced-члена при его рестарте не засчитан ему как падение; watchdog жив.
  H5  поздний heartbeat старого pid: лист и пометка нового воплощения целы; его статус — xfail (вне 1.8b).

Любой сценарий идёт в daemon-потоке с join-дедлайном (``_bounded``); ожидаемые значения — литералы.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from ..monitor.process_monitor import ProcessMonitor
from ._real_state_helpers import attach_real_srm
from .test_run_commands import make_readiness_pm
from .test_supervisor_restart_incarnation import _BACKOFF_S, _DEADLINE_S, _NAME, _bounded, _Registry, _Rig

_REPEATS = 50


# --------------------------------------------------------------------------- #
# H1. Новое воплощение умирает до первого heartbeat — честное падение
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
@pytest.mark.parametrize("new_exitcode", [-9, -15], ids=["new-killed", "new-sigterm"])
def test_new_incarnation_dying_before_first_heartbeat_counts_as_crash(new_exitcode: int) -> None:
    """Рестарт 1/3 исполнен, новое воплощение (pid 41002) умерло, не успев прислать heartbeat: пометка
    «перезапускается» ещё держит pid 41001, но 41002 — другой pid, значит это падение: ``restarting`` 2/3, два
    ``process.restart``. Проверка «по имени» проглотила бы crash-loop."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()
        rig.crash()
        rig.wait_sends(1)
        rig.execute_restarts()
        assert rig.pid == 41002, "предусловие стенда: рестарт не создал новое воплощение"

        rig.proc.die(new_exitcode)  # heartbeat нового воплощения не приходил
        rig.wait_sends(2)

        assert len(rig.sends()) == 2, f"смерть нового воплощения не засчитана; события {rig.events}"
        assert rig.attempts() == ["1/3", "2/3"], rig.events

    _bounded(scenario)


# --------------------------------------------------------------------------- #
# H2. Настоящий поток монитора: смерть заменяемого воплощения в окне стопа — ровно один рестарт
# --------------------------------------------------------------------------- #


def _run_monitor_thread(monitor: ProcessMonitor) -> tuple[threading.Thread, threading.Event]:
    """Настоящий цикл монитора (``_monitoring_loop``, ``poll_interval`` 0,01) в daemon-потоке."""
    stop, pause = threading.Event(), threading.Event()
    monitor._monitoring = True
    thread = threading.Thread(target=monitor._monitoring_loop, args=(stop, pause), daemon=True, name="monitor-loop")
    thread.start()
    return thread, stop


@pytest.mark.timeout(_DEADLINE_S + 60)
def test_real_monitor_thread_one_restart_per_hang_fifty_times() -> None:
    """Зависание -> монитор (настоящий поток) шлёт рестарт; PM стопит старое воплощение: оно умирает ``-15`` в
    момент, который плавает от повтора к повтору, и остаётся в реестре ещё 30 мс (3 такта монитора). Для каждого из
    50 повторов: ``process.restart`` ровно один, событие ``restarting`` одно (``"1/3"``)."""

    def scenario() -> None:
        for i in range(_REPEATS):
            rig = _Rig()
            rig.boot()
            before_death_s = (i % 5) * 0.01

            def slow_stop(name: str, timeout: float = 5.0, *, mark_reader_gone: bool = True, rig=rig, d=before_death_s):
                proc = rig.registry.get_process_by_name(name)
                time.sleep(d)
                proc.die(-15)
                time.sleep(0.03)  # старое воплощение мертво и ещё в реестре; монитор тикает
                return True

            rig.registry.stop_one = slow_stop
            thread, stop = _run_monitor_thread(rig.monitor)
            try:
                rig.hang()
                deadline = time.monotonic() + 5.0
                while len(rig.sends()) < 1 and time.monotonic() < deadline:
                    time.sleep(0.01)
                rig.execute_restarts()
                rig.beat()
                time.sleep(_BACKOFF_S * 3)  # окно, в которое лишний рестарт успел бы запланироваться и уйти
            finally:
                stop.set()
                thread.join(2.0)
            assert not thread.is_alive(), f"повтор {i}: поток монитора не остановился"
            assert len(rig.sends()) == 1, f"повтор {i}: sends={len(rig.sends())}; события {rig.events}"
            assert rig.attempts() == ["1/3"], f"повтор {i}: {rig.events}"

    _bounded(scenario, deadline_s=_DEADLINE_S + 30)


# --------------------------------------------------------------------------- #
# H3. Один и тот же мёртвый объект на многих тактах — одно событие
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
@pytest.mark.parametrize(("exitcode", "crashed_events"), [(-9, 1), (0, 0)], ids=["killed", "clean-exit"])
def test_one_dead_object_over_many_ticks_gives_single_event(exitcode: int, crashed_events: int) -> None:
    """Объект умер и виден монитору на 30 тактах подряд: событие ``crashed`` — ровно одно при ``-9`` и ни одного при
    выходе с кодом 0 (``stopped``); попытка рестарта — одна при ``-9`` и ни одной при 0."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()
        rig.proc.die(exitcode)
        rig.ticks(30)

        crashed = [e for e in rig.events if e[0] == "crashed"]
        assert len(crashed) == crashed_events, rig.events
        assert len(rig.attempts()) == crashed_events, rig.events
        assert rig.statuses()["previous_states"] == ("crashed" if exitcode else "stopped"), rig.statuses()

    _bounded(scenario)


# --------------------------------------------------------------------------- #
# H4. Каскад rest_for_one: induced-член не получает «падения» от собственного рестарта
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_cascade_induced_member_exit_during_its_restart_is_not_a_crash() -> None:
    """``seg`` зависит от ``cam`` (``rest_for_one``). ``cam`` падает -> рестарт ``cam`` 1/3 и induced-рестарт ``seg``.
    Живой ``seg`` умирает ``-15`` при стопе рестарта, монитор тикает параллельно: событий ``crashed`` у ``seg`` нет,
    его событие ровно одно (``restarting`` ``induced``); watchdog (``_recovery_deadline``) держится до heartbeat
    нового воплощения, затем ``recovered``; статус обоих — ``running``, ``process.restart`` ровно два."""

    def scenario() -> None:
        policy = {"enabled": True, "max_retries": 3, "backoff_sec": _BACKOFF_S, "window_sec": 3600.0}
        configs = {
            "cam": {"class": "pkg.Cam", "restart_policy": {**policy, "strategy": "rest_for_one"}},
            "seg": {"class": "pkg.Seg", "depends_on": ["cam"], "restart_policy": dict(policy)},
        }
        pm, monitor = make_readiness_pm(configs)
        attach_real_srm(pm, configs)
        pids = [41000]
        registry = _Registry(pids)
        for name in configs:
            registry.create_and_register(name, "pkg.X").start()
        pm._process_registry = registry
        events: list[tuple[str, str, Any]] = []
        original = monitor._emit_supervisor_event

        def spy(process_name: str, event: str, **kwargs: Any) -> None:
            events.append((process_name, event, kwargs.get("attempt")))
            original(process_name, event, **kwargs)

        monitor._emit_supervisor_event = spy

        def beat(name: str) -> None:
            monitor._on_heartbeat_received(
                {
                    "sender": name,
                    "timestamp": time.time(),
                    "pid": registry.get_process_by_name(name).pid,
                    "status": "running",
                    "readiness": {"ready": True, "reasons": [], "paused": False, "at": time.time()},
                }
            )

        def tick(n: int = 1) -> None:
            for _ in range(n):
                with monitor._iteration_lock:
                    monitor._run_iteration()

        def status(name: str) -> str | None:
            return (monitor.previous_states.get(name) or {}).get("status")

        beat("cam")
        beat("seg")
        tick(2)
        assert (status("cam"), status("seg")) == ("running", "running"), "предусловие стенда: boot не довёл до running"

        registry.get_process_by_name("cam").die(-9)
        deadline = time.monotonic() + 5.0
        sent: list[Any] = []
        while len(sent) < 2 and time.monotonic() < deadline:
            time.sleep(_BACKOFF_S)
            tick()
            sent = [
                c.args[1]
                for c in pm.communication.send_message.call_args_list
                if isinstance(c.args[1], dict) and c.args[1].get("command") == "process.restart"
            ]
        assert len(sent) == 2, f"каскад не отправил два рестарта: {events}"

        registry.stop_exitcode = -15
        registry.during_stop = lambda: tick(3)  # монитор тикает, пока PM стопит
        for msg in sent:
            assert pm._cmd_process_restart(msg["data"])["success"] is True
        registry.during_stop = None
        assert "seg" in monitor._recovery_deadline, "watchdog H3 снят до heartbeat нового воплощения"

        beat("cam")
        beat("seg")
        tick(3)

        seg_events = [(e, a) for n, e, a in events if n == "seg"]
        assert seg_events == [("restarting", "induced"), ("recovered", None)], events
        assert "seg" not in monitor._recovery_deadline
        assert (status("cam"), status("seg")) == ("running", "running")
        assert len(pm.communication.send_message.call_args_list) >= 2
        again = [
            c for c in pm.communication.send_message.call_args_list if c.args[1].get("command") == "process.restart"
        ]
        assert len(again) == 2, f"лишний рестарт: {events}"

    _bounded(scenario)


# --------------------------------------------------------------------------- #
# H5. Поздний heartbeat старого pid
# --------------------------------------------------------------------------- #


def _restarted_rig() -> _Rig:
    """cam упал, рестарт 1/3 исполнен: в реестре новое воплощение 41002, пометка держит 41001, heartbeat новой нет."""
    rig = _Rig()
    rig.boot()
    rig.crash()
    rig.wait_sends(1)
    rig.execute_restarts()
    assert rig.pid == 41002, "предусловие стенда: рестарт не создал новое воплощение"
    rig.tick()
    return rig


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_late_old_pid_heartbeat_does_not_touch_new_incarnation_leaf_or_mark() -> None:
    """Heartbeat старого pid 41001 приходит после рестарта: лист нового воплощения не появляется, пометка
    «перезапускается» остаётся, ``recovered`` нет; heartbeat нового pid 41002 лист принимает и пометку снимает."""

    def scenario() -> None:
        rig = _restarted_rig()
        rig.beat(pid=41001)  # поздний heartbeat старого воплощения
        leaves, restarting = rig.monitor.readiness_view()
        assert (leaves, restarting) == ({}, frozenset({_NAME})), (leaves, restarting)
        rig.tick()
        assert ("recovered", None) not in rig.events, rig.events

        rig.beat(pid=41002)  # первый heartbeat нового воплощения
        leaves, restarting = rig.monitor.readiness_view()
        assert (sorted(leaves), restarting) == ([_NAME], frozenset()), (leaves, restarting)

    _bounded(scenario)


@pytest.mark.xfail(
    strict=True,
    reason="1.8b OUT OF SCOPE (H5): _on_heartbeat_received пишет reported_status (paused/running) в previous_states "
    "без проверки pid воплощения; поздний heartbeat старого pid со status=paused до такта монитора выдаёт "
    "новому воплощению чужой статус. Лист и пометка защищены в 1.7c (_accept_readiness), статус — нет.",
)
@pytest.mark.timeout(_DEADLINE_S + 30)
def test_late_old_pid_heartbeat_status_does_not_overwrite_new_incarnation_status() -> None:
    """Поздний heartbeat старого pid 41001 со ``status: paused`` не меняет статус нового воплощения (``running``)."""

    def scenario() -> None:
        rig = _restarted_rig()
        assert rig.statuses()["previous_states"] == "running", rig.statuses()
        now = time.time()
        rig.monitor._on_heartbeat_received({"sender": _NAME, "timestamp": now, "pid": 41001, "status": "paused"})
        assert rig.statuses()["previous_states"] == "running", rig.statuses()

    _bounded(scenario)
