# -*- coding: utf-8 -*-
"""Авторские hazard-тесты Task 1.4 для BackendHarness (ADR-PMM-031, звено 3).

Цель — сторожить правки harness'а В ИЗОЛЯЦИИ. Штатно зависшего ребёнка добивает
guard spawner'а (звенья 1+2), и harness-тесты тестера зеленеют без правок harness'а
(проверено инъекцией). Поэтому здесь ``launcher.shutdown`` подменён: spawner и его
guard НЕ работают, единственная страховка — ``_force_kill_tree`` harness'а.

Каждый сценарий построен так, чтобы до цели дотягивался ровно один механизм:

* T1 — внук в ГРУППЕ PM, рождён после досъёма, PM убит извне → только ``killpg``.
* T2 — ребёнок сделал свой ``setsid`` (вне группы), PM убит извне → только снимок
  после готовности.
* T3 — внук со своим ``setsid``, рождён после готовности, PM жив до stop(), shutdown
  убивает только PM → только досъём в ``stop()``.

Файл самодостаточный: из тестов framework ничего не импортирует.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

import pytest

from backend_ctl import harness as harness_mod
from backend_ctl.harness import BackendHarness
from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import SystemLauncher

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: setsid/killpg")

_PIDFILE_ENV = "HARNESS_HAZARD_PIDFILE"
_MOD = "backend_ctl.tests.test_harness_no_orphans_hazards"
# Задержка рождения внука: заведомо после досъёма снимка по готовности.
_LATE_SPAWN_S = 2.5
_SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]


def _write_pid(pid: int) -> None:
    path = os.environ[_PIDFILE_ENV]
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(str(pid))
    os.replace(tmp, path)


class _ChildBase:
    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:  # pragma: no cover
        pass

    def shutdown(self) -> None:  # pragma: no cover
        pass

    @staticmethod
    def _forever() -> None:
        while True:
            time.sleep(3600)


class LateGroupGrandchild(_ChildBase):
    """T1: через паузу рождает внука В группе PM (без своей сессии)."""

    def run(self) -> None:
        time.sleep(_LATE_SPAWN_S)
        _write_pid(subprocess.Popen(_SLEEPER).pid)
        self._forever()


class SetsidChild(_ChildBase):
    """T2: сам уходит из группы PM (своя сессия)."""

    def run(self) -> None:
        os.setsid()
        _write_pid(os.getpid())
        self._forever()


class LateSetsidGrandchild(_ChildBase):
    """T3: через паузу рождает внука в СВОЕЙ сессии (вне группы PM)."""

    def run(self) -> None:
        time.sleep(_LATE_SPAWN_S)
        _write_pid(subprocess.Popen(_SLEEPER, start_new_session=True).pid)
        self._forever()


# ---------------------------------------------------------------------------
# Обвязка
# ---------------------------------------------------------------------------


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _kill(pid: Optional[int]) -> None:
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        import psutil

        psutil.Process(pid).wait(timeout=2.0)
    except Exception:  # noqa: BLE001
        pass


def _wait_pidfile(path: Path, deadline_s: float = 15.0) -> int:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if path.exists():
            return int(path.read_text())
        time.sleep(0.05)
    raise AssertionError("ребёнок не записал pid — сценарий не поднялся, не целевой баг")


def _alive_after(proc: Any, deadline_s: float = 3.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        if not proc.is_running():
            return False
        time.sleep(0.05)
    return proc.is_running()


class _Run:
    """Harness + launcher с подменённым shutdown; уборка всего в teardown."""

    def __init__(self, child_class: str, fake_shutdown) -> None:
        self.launcher: Optional[SystemLauncher] = None
        self._real_shutdown = None
        self._fake = fake_shutdown

        def factory() -> SystemLauncher:
            launcher = SystemLauncher(config={"c": {"class": f"{_MOD}.{child_class}"}}, stop_timeout=5.0)
            self._real_shutdown = launcher.shutdown
            launcher.shutdown = lambda: self._fake(launcher)  # spawner и его guard не работают
            self.launcher = launcher
            return launcher

        self.harness = BackendHarness(
            launcher_factory=factory, port=_free_port(), ready_timeout=20.0, teardown_timeout=5.0
        )
        self.extra: List[Any] = []

    def pm_pid(self) -> int:
        assert self.launcher is not None
        return self.launcher._spawner.get_process().pid

    def cleanup(self) -> None:
        for p in self.extra:
            try:
                if p.is_running():
                    _kill(p.pid)
            except Exception:  # noqa: BLE001
                pass
        if self.launcher is not None and self._real_shutdown is not None:
            # Настоящий stop: guard spawner'а + SRM. В потоке с дедлайном — не виснуть.
            t = threading.Thread(target=self._real_shutdown, daemon=True)
            t.start()
            t.join(timeout=20.0)


def _noop_shutdown(_launcher) -> None:
    return None


def _kill_pm_only(launcher) -> None:
    proc = launcher._spawner.get_process()
    _kill(proc.pid)
    proc.join(timeout=2.0)


def _pids(procs: List[Any]) -> set:
    return {getattr(p, "pid", None) for p in procs}


# ---------------------------------------------------------------------------
# T1 — killpg группы PM
# ---------------------------------------------------------------------------


@pytest.mark.timeout(90)
def test_group_member_absent_from_snapshots_dies_via_killpg(tmp_path, monkeypatch):
    """Сторожит: вызов ``_kill_orchestrator_group`` в ``_force_kill_tree``."""
    import psutil

    pidfile = tmp_path / "gc.pid"
    monkeypatch.setenv(_PIDFILE_ENV, str(pidfile))
    run = _Run("LateGroupGrandchild", _noop_shutdown)
    try:
        run.harness.start()
        pm = run.pm_pid()
        gc = psutil.Process(_wait_pidfile(pidfile))
        run.extra.append(gc)
        assert gc.pid not in _pids(run.harness._descendants), "внук попал в снимок — сценарий вакуумен"
        assert os.getpgid(gc.pid) == pm, "внук не в группе PM — сценарий не тот"

        _kill(pm)  # PM убит извне: живого поддерева нет, досъём в stop() пуст
        run.harness.stop()

        assert not _alive_after(gc), f"внук группы PM pid={gc.pid} пережил harness.stop()"
    finally:
        run.cleanup()


# ---------------------------------------------------------------------------
# T2 — снимок после готовности
# ---------------------------------------------------------------------------


@pytest.mark.timeout(90)
def test_setsid_child_dies_via_post_readiness_snapshot(tmp_path, monkeypatch):
    """Сторожит: ``_union(...)`` сразу после ``wait_until_ready`` в ``start()``."""
    import psutil

    pidfile = tmp_path / "child.pid"
    monkeypatch.setenv(_PIDFILE_ENV, str(pidfile))
    run = _Run("SetsidChild", _noop_shutdown)
    try:
        run.harness.start()
        pm = run.pm_pid()
        child = psutil.Process(_wait_pidfile(pidfile))
        run.extra.append(child)
        assert os.getpgid(child.pid) != pm, "ребёнок остался в группе PM — killpg маскирует снимок"

        _kill(pm)
        run.harness.stop()

        assert not _alive_after(child), f"ребёнок со своим setsid pid={child.pid} пережил harness.stop()"
    finally:
        run.cleanup()


# ---------------------------------------------------------------------------
# T3 — досъём в stop()
# ---------------------------------------------------------------------------


@pytest.mark.timeout(90)
def test_late_setsid_grandchild_dies_via_stop_refresh(tmp_path, monkeypatch):
    """Сторожит: ``_union(...)`` перед ``_shutdown_with_watchdog`` в ``stop()``."""
    import psutil

    pidfile = tmp_path / "gc.pid"
    monkeypatch.setenv(_PIDFILE_ENV, str(pidfile))
    run = _Run("LateSetsidGrandchild", _kill_pm_only)
    try:
        run.harness.start()
        pm = run.pm_pid()
        gc = psutil.Process(_wait_pidfile(pidfile))
        run.extra.append(gc)
        assert gc.pid not in _pids(run.harness._descendants), "внук попал в снимок до stop() — сценарий вакуумен"
        assert os.getpgid(gc.pid) != pm, "внук в группе PM — killpg маскирует досъём"

        run.harness.stop()  # PM жив до этой строки; shutdown убивает только PM

        assert not _alive_after(gc), f"внук со своим setsid pid={gc.pid} пережил harness.stop()"
    finally:
        run.cleanup()


# ---------------------------------------------------------------------------
# Белый ящик: объединение и защита своей группы
# ---------------------------------------------------------------------------


def test_union_keeps_early_entries_first_and_drops_duplicates():
    """Сторожит: ``out = list(first)`` в ``_union`` (ранний снимок не выбрасывается)."""
    early_pm, child = object(), object()
    assert harness_mod._union([early_pm], [child, early_pm]) == [early_pm, child]
    assert harness_mod._union([early_pm], []) == [early_pm]


def test_group_sweep_never_targets_own_group(monkeypatch):
    """Сторожит: ``orchestrator_pid == os.getpgrp()`` в ``_kill_orchestrator_group``."""
    calls = []
    monkeypatch.setattr(harness_mod.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))
    harness_mod._kill_orchestrator_group(os.getpgrp(), log=lambda _m: None)
    assert calls == []
