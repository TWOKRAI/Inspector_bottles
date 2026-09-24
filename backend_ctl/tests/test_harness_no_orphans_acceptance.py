# -*- coding: utf-8 -*-
"""Acceptance-тесты Task 1.4 (`lifecycle-stop-ownership`) для BackendHarness: «ни один
путь остановки не оставляет процессов-сирот». Независимый тестер, контракт — из
брифа/handoff (docs/handoffs/2026-09-24_task-1.4-tester.md), план НЕ читался.

Самодостаточный файл (брифом ЗАПРЕЩЕН импорт из multiprocess_framework/.../tests/ —
дублирует HungChild/снимок-хелперы, а не переиспользует
``_no_orphans_helpers.py`` из соседнего модуля). Небольшое дублирование с
``multiprocess_framework/modules/process_manager_module/tests/_no_orphans_helpers.py``
принято сознательно.
"""

from __future__ import annotations

import os
import signal
import sys
import time
from typing import Any, List, Optional

import pytest

from backend_ctl.harness import BackendHarness
from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import SystemLauncher

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: setsid/killpg/SIGKILL semantics")

HUNG_CHILD_CLASS_PATH = "backend_ctl.tests.test_harness_no_orphans_acceptance.HungChild"


class HungChild:
    """Дублирует ``_no_orphans_helpers.HungChild`` (framework tests) — дочерний
    процесс, который НЕ уходит ни по ``stop_event``, ни по SIGTERM (SIG_IGN).
    Дублирование сознательное — файл self-contained по брифу.
    """

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        import signal as _signal
        import time as _time

        _signal.signal(_signal.SIGTERM, _signal.SIG_IGN)
        while True:
            _time.sleep(3600)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:  # pragma: no cover
        pass

    def shutdown(self) -> None:  # pragma: no cover
        pass


def _snapshot_children(orchestrator_pid: int) -> List[Any]:
    try:
        import psutil

        return psutil.Process(orchestrator_pid).children(recursive=True)
    except Exception:  # noqa: BLE001
        return []


def _alive_pids(procs: List[Any]) -> List[int]:
    alive: List[int] = []
    for p in procs:
        try:
            if p.is_running():
                alive.append(p.pid)
        except Exception:  # noqa: BLE001
            pass
    return alive


def _wait_until_gone(procs: List[Any], deadline_s: float, poll_s: float = 0.05) -> List[int]:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        survivors = _alive_pids(procs)
        if not survivors:
            return []
        time.sleep(poll_s)
    return _alive_pids(procs)


def _kill_and_reap(pid: Optional[int]) -> None:
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        import psutil

        psutil.Process(pid).wait(timeout=2.0)
    except Exception:  # noqa: BLE001
        pass


def _cleanup_procs(procs: List[Any]) -> None:
    for p in procs:
        try:
            if p.is_running():
                _kill_and_reap(p.pid)
        except Exception:  # noqa: BLE001
            pass


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_harness() -> BackendHarness:
    port = _free_port()
    factory = lambda: SystemLauncher(config={"hung": {"class": HUNG_CHILD_CLASS_PATH}}, stop_timeout=5.0)
    return BackendHarness(launcher_factory=factory, port=port, ready_timeout=20.0, teardown_timeout=10.0)


# ---------------------------------------------------------------------------
# A1 — harness.stop() c зависшим ребёнком: 0 живых процессов этого запуска.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_harness_stop_leaves_no_orphan_with_hung_child():
    harness = _make_harness()
    snap: List[Any] = []
    orch_pid: Optional[int] = None
    try:
        harness.start()
        orch_pid = harness._orch_pid  # white-box: тест ИМЕННО о внутреннем pid harness'а
        assert orch_pid is not None, "harness.start() не выставил _orch_pid — окружение сломано"
        snap = _snapshot_children(orch_pid)
        assert snap, "снимок поддерева пуст ДО остановки — не удалось поймать зависшего ребёнка живым"

        harness.stop()

        survivors = _wait_until_gone(snap, deadline_s=3.0)
        assert survivors == [], f"остались живые PID после harness.stop(): {survivors}"
    finally:
        _cleanup_procs(snap)
        if orch_pid is not None:
            _kill_and_reap(orch_pid)


# ---------------------------------------------------------------------------
# A5 — PM убит SIGKILL извне, затем harness.stop(): harness восстанавливается
# и всё равно добивает поддерево (0 живых).
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_harness_stop_recovers_after_pm_killed_externally():
    harness = _make_harness()
    snap: List[Any] = []
    orch_pid: Optional[int] = None
    try:
        harness.start()
        orch_pid = harness._orch_pid
        assert orch_pid is not None, "harness.start() не выставил _orch_pid — окружение сломано"
        snap = _snapshot_children(orch_pid)
        assert snap, "снимок поддерева пуст ДО остановки — не удалось поймать зависшего ребёнка живым"

        os.kill(orch_pid, signal.SIGKILL)
        time.sleep(0.3)  # дать ОС завершить реап/репарентинг

        harness.stop()

        survivors = _wait_until_gone(snap, deadline_s=3.0)
        assert survivors == [], (
            f"остались живые PID после harness.stop() (PM убит внешним SIGKILL до stop()): {survivors}"
        )
    finally:
        _cleanup_procs(snap)
        if orch_pid is not None:
            _kill_and_reap(orch_pid)
