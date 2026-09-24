# -*- coding: utf-8 -*-
"""Авторские hazard-тесты Task 1.4 (ADR-PMM-031): что может сломаться В ЭТОМ механизме.

Каждый тест называет строку правки, которую он сторожит (поле «Сторожит»).
Независимые acceptance-тесты — в ``test_no_orphans_acceptance.py``; эти — дополнение.

Механизм:
* внешний join spawner'а выводится из графика внутренней эскалации PM
  (``outer_stop_budget``), а PM получает тот же graceful-бюджет через конфиг;
* guard после сбора лидера бьёт группу по ``pgid == pm_pid`` и всегда добивает
  живых членов снимка.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from ..core.process_registry import KILL_CONFIRM_S, TERMINATE_GRACE_S
from ..launcher import process_tree_guard as guard_mod
from ..launcher.process_tree_guard import ProcessTreeGuard
from ..launcher.spawner import PM_TEARDOWN_MARGIN_S, ProcessSpawner, outer_stop_budget
from ._no_orphans_helpers import kill_and_reap

_SPAWNER = "multiprocess_framework.modules.process_manager_module.launcher.spawner"


# ---------------------------------------------------------------------------
# Бюджеты: внешний строго больше внутреннего, одна формула для всех путей.
# ---------------------------------------------------------------------------


def test_outer_budget_literal_for_defaults():
    """Литерал, а не выражение из кода: 5.0 + 1.0 + 1.0 + 1.5 = 8.5.

    Сторожит: ``outer_stop_budget`` и значения трёх констант. Смена любого окна
    обязана пройти через ревью этого числа.
    """
    assert (TERMINATE_GRACE_S, KILL_CONFIRM_S, PM_TEARDOWN_MARGIN_S) == (1.0, 1.0, 1.5)
    assert outer_stop_budget(5.0) == 8.5


@pytest.mark.parametrize("graceful", [0.1, 1.0, 5.0, 10.0, 30.0])
def test_outer_budget_strictly_exceeds_inner_escalation(graceful):
    """Сторожит: слагаемое ``PM_TEARDOWN_MARGIN_S`` (> 0) в ``outer_stop_budget``.

    Внутренняя эскалация ``_stop_many`` = graceful + TERMINATE_GRACE_S + KILL_CONFIRM_S.
    """
    inner = graceful + TERMINATE_GRACE_S + KILL_CONFIRM_S
    assert outer_stop_budget(graceful) > inner
    assert outer_stop_budget(graceful) - inner >= 1.0


def _launch_capture_config(spawner: ProcessSpawner) -> dict:
    """launch_orchestrator() на моках; вернуть process_config, ушедший в Process."""
    with (
        patch.object(spawner, "_platform"),
        patch.object(spawner, "_setup_signals"),  # не ставить реальные обработчики в pytest
        patch(f"{_SPAWNER}.Process") as MockProcess,
        patch(f"{_SPAWNER}.SharedResourcesManager") as MockSRM,
        patch(f"{_SPAWNER}.ProcessTreeGuard"),
    ):
        MockSRM.return_value = MagicMock()
        MockProcess.return_value = MagicMock(pid=12345)
        spawner.launch_orchestrator()
        bundle = MockProcess.call_args[1]["args"][3]
        return bundle["config"]


def test_pm_receives_spawner_graceful_budget_by_default():
    """Сторожит: ``process_config["shutdown_timeout"] = self._stop_timeout`` в launch.

    Без этой строки PM читает свой дефолт 5.0 независимо от stop_timeout spawner'а —
    при stop_timeout=12 внутренний бюджет разошёлся бы с тем, из чего выведен внешний.
    """
    spawner = ProcessSpawner(stop_timeout=12.0)
    cfg = _launch_capture_config(spawner)
    assert cfg["shutdown_timeout"] == 12.0


def test_explicit_orchestrator_shutdown_timeout_wins_and_drives_join():
    """Сторожит: условие ``is None`` (явный бюджет оркестратора не перетирается)
    и ``_pm_graceful_budget`` (внешний join считается от бюджета PM, не от stop_timeout).
    """
    spawner = ProcessSpawner(stop_timeout=5.0, orchestrator_config={"shutdown_timeout": 9.0})
    cfg = _launch_capture_config(spawner)
    assert cfg["shutdown_timeout"] == 9.0

    proc = MagicMock()
    proc.is_alive.side_effect = [True, False, False]
    spawner._process = proc
    spawner._guard = MagicMock()
    spawner._shared_resources = None
    spawner.stop()
    proc.join.assert_called_once_with(timeout=12.5)  # 9.0 + 1.0 + 1.0 + 1.5


def test_default_stop_join_is_outer_budget():
    """Сторожит: ``effective_timeout = outer_stop_budget(graceful)`` в stop().

    До правки join был равен голому stop_timeout (5.0) — меньше внутренних 7.0.
    """
    spawner = ProcessSpawner(stop_timeout=5.0)
    proc = MagicMock()
    proc.is_alive.side_effect = [True, False, False]
    spawner._process = proc
    spawner.stop()
    proc.join.assert_called_once_with(timeout=8.5)


def test_explicit_stop_timeout_goes_through_formula():
    """Сторожит: явный ``stop(timeout=...)`` — graceful-бюджет, а не голый join."""
    spawner = ProcessSpawner(stop_timeout=5.0)
    proc = MagicMock()
    proc.is_alive.side_effect = [True, False, False]
    spawner._process = proc
    spawner.stop(timeout=2.0)
    proc.join.assert_called_once_with(timeout=5.5)  # 2.0 + 1.0 + 1.0 + 1.5


# ---------------------------------------------------------------------------
# Guard: не бить свою группу; добивать снимок и при успешном примитиве.
# ---------------------------------------------------------------------------

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX: killpg/setsid")


@posix_only
def test_guard_never_killpg_launcher_group_when_leader_reaped(monkeypatch):
    """Сторожит: проверку ``pgid == os.getpgrp()`` ПОСЛЕ ветки ProcessLookupError.

    Если бы защита осталась только в ветке «getpgid удался», pid PM, совпавший с
    группой launcher'а, повёл бы killpg в собственную группу pytest.
    """
    calls = []

    def _no_such(_pid):
        raise ProcessLookupError

    monkeypatch.setattr(guard_mod.os, "getpgid", _no_such)
    monkeypatch.setattr(guard_mod.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    guard = ProcessTreeGuard()
    guard.adopt(os.getpgrp())
    assert guard._terminate_posix_group() is False
    assert calls == []


@posix_only
def test_guard_never_killpg_launcher_group_when_getpgid_succeeds(monkeypatch):
    """Сторожит: ту же проверку на пути, где getpgid вернул группу launcher'а."""
    calls = []
    monkeypatch.setattr(guard_mod.os, "getpgid", lambda _pid: os.getpgrp())
    monkeypatch.setattr(guard_mod.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    guard = ProcessTreeGuard()
    guard.adopt(99999)
    assert guard._terminate_posix_group() is False
    assert calls == []


@posix_only
@pytest.mark.timeout(30)
def test_guard_sweeps_snapshot_member_outside_group_when_primitive_succeeds():
    """Сторожит: ветку ``else: self._sweep_snapshot(...)`` в kill_tree.

    Член снимка сделал свой setsid (вне группы PM). Группа PM пуста → killpg
    даёт ProcessLookupError → примитив «сработал» (True). До правки psutil-путь
    на этом месте не звался, и такой член переживал teardown.
    """
    import psutil

    leader = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    leader.wait(timeout=10)  # лидер собран, группа пуста
    stray = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    try:
        member = psutil.Process(stray.pid)
        guard = ProcessTreeGuard()
        guard.adopt(leader.pid)
        guard.kill_tree([member])
        stray.wait(timeout=5)  # реап; TimeoutExpired = член выжил
        assert stray.returncode is not None
    finally:
        if stray.poll() is None:
            kill_and_reap(stray.pid)
            stray.wait(timeout=5)


@posix_only
def test_guard_sweep_skips_own_pid():
    """Сторожит: ``proc.pid != me`` в ``_sweep_snapshot`` — снимок с самим launcher'ом
    (ошибочный вызов) не убивает launcher.
    """
    me = MagicMock(pid=os.getpid())
    ProcessTreeGuard()._sweep_snapshot([me])
    me.kill.assert_not_called()


@posix_only
@pytest.mark.timeout(30)
def test_guard_on_normal_path_does_not_sleep_when_group_empty():
    """Сторожит стоимость штатного стопа: пустая группа → killpg(SIGTERM) сразу
    даёт ProcessLookupError → без ``sleep(0.5)``. Иначе каждый штатный стоп + 0.5с.
    """
    leader = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    leader.wait(timeout=10)
    guard = ProcessTreeGuard()
    guard.adopt(leader.pid)
    t0 = time.monotonic()
    guard.kill_tree([])
    assert time.monotonic() - t0 < 0.3
