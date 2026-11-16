# -*- coding: utf-8 -*-
"""fix-B3 / F4 (свежее ревью Ф1 run-state): провал ``restart_process`` не оставляет пометку «перезапускается».

``restart_process`` ставит пометку ``mark_restarting`` ДО замены воплощения. Успех снимает её heartbeat нового pid, а
провал (``stop_process`` ложь, ``create_and_register`` ``None``, исключение) раньше не снимал никто: heartbeat живого
процесса отбрасывался как «чужой», в причинах навсегда «перезапускается супервизором». Теперь каждый выход-провал после
пометки зовёт ``ProcessMonitor.unmark_restarting``.

Обвязка — ``_Rig`` слепых тестов 1.8b: настоящие ``ProcessManagerProcess.restart_process``, ``ProcessMonitor``,
``SharedResourcesManager``; двойники — процесс ОС и реестр OS-процессов. Ожидания — литералы.
"""

from __future__ import annotations

import pytest

from .test_supervisor_restart_incarnation import _DEADLINE_S, _NAME, _bounded, _Rig


def _assert_unmarked_and_alive_heartbeat_accepted(rig: _Rig) -> None:
    """Пометки нет; heartbeat процесса (pid прежнего воплощения 41001) принят; причины не говорят «перезапускается»."""
    assert rig.monitor.readiness_view()[1] == frozenset()
    assert rig.monitor.get_stats()["last_heartbeats"].get(_NAME) is None, "предусловие: база heartbeat сброшена"
    rig.beat(pid=41001)
    assert rig.monitor.get_stats()["last_heartbeats"][_NAME] < 5.0
    rig.tick()
    texts = [r["reason"] for r in rig.pm._cmd_system_run_status()["reasons"]]
    assert not any("перезапускается" in t for t in texts), texts


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_restart_process_stop_refused_unmarks() -> None:
    """``stop_process`` -> ``False`` (старое воплощение не подтвердило смерть): ``restart_process`` -> ``False``;
    пометки нет, heartbeat живого процесса принимается, причина «перезапускается» исчезла (процесс жив, причин нет)."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()
        rig.pm.stop_process = lambda *args, **kwargs: False

        assert rig.pm.restart_process(_NAME) is False

        _assert_unmarked_and_alive_heartbeat_accepted(rig)
        assert [r["reason"] for r in rig.pm._cmd_system_run_status()["reasons"]] == []

    _bounded(scenario)


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_restart_process_create_returns_none_unmarks() -> None:
    """``create_and_register`` -> ``None`` (воплощение не создано): ``restart_process`` -> ``False``; пометки нет, а
    причина честная — «процесс не жив» (старое воплощение уже убрано из реестра), не «перезапускается»."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()
        rig.registry.create_and_register = lambda *args, **kwargs: None

        assert rig.pm.restart_process(_NAME) is False

        _assert_unmarked_and_alive_heartbeat_accepted(rig)
        assert [r["reason"] for r in rig.pm._cmd_system_run_status()["reasons"]] == ["процесс не жив"]

    _bounded(scenario)


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_restart_process_create_raises_unmarks_and_propagates() -> None:
    """``create_and_register`` бросает: исключение уходит вызывающему (как раньше), но пометки нет."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()

        def boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("boom")

        rig.registry.create_and_register = boom

        with pytest.raises(RuntimeError, match="boom"):
            rig.pm.restart_process(_NAME)

        _assert_unmarked_and_alive_heartbeat_accepted(rig)

    _bounded(scenario)


@pytest.mark.timeout(_DEADLINE_S + 30)
def test_restart_process_success_keeps_mark_until_new_pid_heartbeat() -> None:
    """Охрана: успешный рестарт пометку НЕ снимает сам — её снимает первый heartbeat нового pid (41002)."""

    def scenario() -> None:
        rig = _Rig()
        rig.boot()

        assert rig.pm.restart_process(_NAME) is True

        assert rig.pid == 41002, "предусловие стенда: рестарт создал новое воплощение"
        assert rig.monitor.readiness_view()[1] == frozenset({_NAME})
        rig.beat(pid=41002)
        assert rig.monitor.readiness_view()[1] == frozenset()

    _bounded(scenario)
