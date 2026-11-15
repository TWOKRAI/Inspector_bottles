# -*- coding: utf-8 -*-
"""fix-B / M3 + m3 (ревью Ф1 run-state): забор воплощения на ВХОДЕ heartbeat; пометка после ``gave_up``.

M3: heartbeat чужого воплощения (pid целый и не равен pid реестра, либо процесс «перезапускается» и pid не новый) не
трогает ни время последнего heartbeat, ни статус, ни лист готовности, ни пометку «перезапускается». Раньше проверка
стояла только при приёме листа: время и статус принимали heartbeat старого воплощения.

m3: после ``gave_up`` супервизор сдался — пометка «перезапускается» снята, причина процесса — «процесс не жив», а не
«перезапускается супервизором».

Обвязка — настоящие ``ProcessMonitor`` + ``SharedResourcesManager`` + ``PM.restart_process`` (``_Rig`` слепых тестов
1.8b); двойники — процесс ОС и реестр OS-процессов. Ожидания — литералы; зависание — daemon-поток с join-дедлайном.
"""

from __future__ import annotations

import time

import pytest

from .test_supervisor_restart_incarnation import _DEADLINE_S, _NAME, _bounded, _Rig
from .test_supervisor_restart_incarnation_hazards import _restarted_rig


def _heartbeat_age_s(rig: _Rig) -> float | None:
    """Возраст последнего принятого heartbeat ``cam`` (публичный ``get_stats``); ``None`` — не принимался."""
    return rig.monitor.get_stats()["last_heartbeats"].get(_NAME)


# --------------------------------------------------------------------------- #
# M3. Чужой heartbeat не трогает время, статус, лист
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_foreign_pid_heartbeat_does_not_touch_last_heartbeat() -> None:
    """Рестарт исполнен: в реестре 41002, пометка держит 41001, базу heartbeat монитор сбросил. Поздний heartbeat
    старого pid 41001 базу не поднимает: heartbeat у ``cam`` нет, пометка и лист на месте (``recovered`` не будет)."""

    def scenario() -> None:
        rig = _restarted_rig()
        assert _heartbeat_age_s(rig) is None, "предусловие стенда: база heartbeat не сброшена"

        rig.beat(pid=41001)

        assert _heartbeat_age_s(rig) is None
        leaves, restarting = rig.monitor.readiness_view()
        assert (leaves, restarting) == ({}, frozenset({_NAME})), (leaves, restarting)

    _bounded(scenario)


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_foreign_pid_heartbeat_outside_restart_does_not_touch_time_or_status() -> None:
    """Вне перезапуска: pid реестра 41001, heartbeat с pid 41999 (чужой) и меткой времени на 100 с старше, со
    ``status: paused``. Ни время (возраст heartbeat остаётся малым), ни статус (``running``) не меняются."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()
        assert rig.pid == 41001, "предусловие стенда"
        assert _heartbeat_age_s(rig) < 5.0

        now = time.time()
        rig.monitor._on_heartbeat_received(
            {"sender": _NAME, "timestamp": now - 100.0, "pid": 41999, "status": "paused"}
        )

        assert _heartbeat_age_s(rig) < 5.0, "чужой heartbeat подменил время последнего heartbeat"
        assert rig.statuses()["previous_states"] == "running", rig.statuses()

    _bounded(scenario)


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_current_pid_heartbeat_after_restart_is_accepted_everywhere() -> None:
    """Охрана: первый heartbeat нового воплощения (41002) со ``status: paused`` принят целиком — база heartbeat
    поднята, пометка снята, лист принят, статус обновлён."""

    def scenario() -> None:
        rig = _restarted_rig()
        now = time.time()
        rig.monitor._on_heartbeat_received(
            {
                "sender": _NAME,
                "timestamp": now,
                "pid": 41002,
                "status": "paused",
                "readiness": {"ready": True, "reasons": [], "paused": False, "at": now},
            }
        )

        assert _heartbeat_age_s(rig) < 5.0
        leaves, restarting = rig.monitor.readiness_view()
        assert (sorted(leaves), restarting) == ([_NAME], frozenset()), (leaves, restarting)
        assert rig.statuses()["previous_states"] == "paused", rig.statuses()

    _bounded(scenario)


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_pidless_heartbeat_outside_restart_is_accepted_as_before() -> None:
    """Старый контракт: heartbeat без ``pid`` вне перезапуска принимается (время, статус, лист), как до правки."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()
        now = time.time()
        rig.monitor._on_heartbeat_received(
            {
                "sender": _NAME,
                "timestamp": now - 100.0,
                "status": "paused",
                "readiness": {"ready": True, "reasons": [], "paused": False, "at": now},
            }
        )

        assert _heartbeat_age_s(rig) > 90.0, "heartbeat без pid не принят (время)"
        assert rig.statuses()["previous_states"] == "paused", rig.statuses()

    _bounded(scenario)


# --------------------------------------------------------------------------- #
# m3. gave_up снимает пометку «перезапускается»
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_gave_up_clears_restarting_reason() -> None:
    """``max_retries`` 1: падение -> рестарт 1/1 исполнен -> новое воплощение (41002) умерло -> лимит исчерпан,
    ``gave_up``. Пометка «перезапускается» снята: в причинах ``cam`` «процесс не жив», слова «перезапускается» нет."""

    def scenario() -> None:
        rig = _Rig(max_retries=1)
        rig.boot()
        rig.crash()
        rig.wait_sends(1)
        rig.execute_restarts()
        assert rig.pid == 41002, "предусловие стенда: рестарт не создал новое воплощение"
        assert rig.monitor.readiness_view()[1] == frozenset({_NAME}), "предусловие: пометка стоит до смерти нового"

        rig.proc.die(-9)  # новое воплощение умерло до первого heartbeat
        deadline = time.monotonic() + 5.0
        while ("gave_up", None) not in rig.events and time.monotonic() < deadline:
            rig.tick()
        assert ("gave_up", None) in rig.events, rig.events

        assert rig.monitor.readiness_view()[1] == frozenset()
        rig.tick()  # следующий такт пересчитывает готовность PM уже без пометки
        reasons = rig.pm._cmd_system_run_status()["reasons"]
        assert [r["reason"] for r in reasons] == ["процесс не жив"], reasons

    _bounded(scenario)
