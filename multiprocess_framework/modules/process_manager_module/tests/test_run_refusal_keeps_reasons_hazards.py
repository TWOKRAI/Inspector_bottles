# -*- coding: utf-8 -*-
"""Phase 1 (system-run-state), C10 — отказ, не меняющий состояние, не пишет причины допуска в статус.

``system.run.start`` / ``system.run.ack`` оценивают готовность по порогу допуска (строже удержания, Task 1.7b). Если
команда отказана и состояние не меняется (``already_running``, ``fault_unacknowledged``, ``fault_stopping``,
``not_ready`` в ``booting``...), причины допуска в ``system.run.status`` попадать не должны: статус отражает последний
такт монитора, а не оценку отказанной команды.

Обвязка — как ``test_run_commands.py``: настоящие ``ProcessManagerProcess`` + ``ProcessMonitor``.
"""

from __future__ import annotations

import pytest

from .test_run_commands import _to_running, beat, make_readiness_pm, tick

_BETWEEN_ADMISSION_AND_HOLD_S = 12.0  # допуск требует лист не старше 10 с, удержание — не старше 15 с


@pytest.mark.timeout(60)
def test_start_in_running_does_not_replace_status_reasons() -> None:
    """``running``, лист ``cam`` возрастом 12 с (удержание держит, допуск не пропустил бы): START ->
    ``already_running``, причины в статусе не меняются (раньше подменялись на ``failure`` «нет отчёта о готовности»)."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    _to_running(pm, monitor)
    beat(monitor, "cam", age_s=_BETWEEN_ADMISSION_AND_HOLD_S)
    tick(pm, monitor)
    assert pm._cmd_system_run_status()["state"] == "running"
    before = pm._cmd_system_run_status()["reasons"]

    reply = pm._cmd_system_run_start()

    assert reply["success"] is False and reply["error"] == "already_running", reply
    assert pm._cmd_system_run_status()["reasons"] == before == []


@pytest.mark.timeout(60)
def test_start_in_fault_does_not_replace_status_reasons() -> None:
    """``fault`` (лист ``cam`` устарел), затем приходит свежий лист; START до следующего такта ->
    ``fault_unacknowledged``, причины статуса остаются причинами аварии (не оценкой START: она бы их очистила)."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}}, run_gate=False)
    _to_running(pm, monitor)
    beat(monitor, "cam", age_s=100.0)
    tick(pm, monitor)
    assert pm._cmd_system_run_status()["state"] == "fault"
    before = pm._cmd_system_run_status()["reasons"]
    assert [r["reason"] for r in before] == ["нет отчёта о готовности"]
    beat(monitor, "cam")  # свежий лист: оценка START дала бы пустые причины

    reply = pm._cmd_system_run_start()

    assert reply["success"] is False and reply["error"] == "fault_unacknowledged", reply
    assert pm._cmd_system_run_status()["reasons"] == before


@pytest.mark.timeout(60)
def test_refused_start_that_changes_state_still_writes_reasons() -> None:
    """Охранный: START из ``ready`` отказан и состояние сменилось на ``not_ready`` -> причины допуска в статусе (они
    объясняют новое состояние)."""
    pm, monitor = make_readiness_pm({"cam": {"class": "pkg.Cam"}})
    beat(monitor, "cam")
    tick(pm, monitor)
    assert pm._cmd_system_run_status()["state"] == "ready"
    beat(monitor, "cam", age_s=_BETWEEN_ADMISSION_AND_HOLD_S)  # лист между порогами: удержание ready, допуск откажет

    reply = pm._cmd_system_run_start()

    assert reply["success"] is False and reply["error"] == "not_ready", reply
    status = pm._cmd_system_run_status()
    assert status["state"] == "not_ready"
    assert [r["reason"] for r in status["reasons"]] == ["нет отчёта о готовности"]
