# -*- coding: utf-8 -*-
"""Acceptance-тесты Task 1.5 (`lifecycle-stop-ownership`) для ``BackendHarness``:
«ни один ребёнок PM не переживает SIGKILL PM». Независимый тестер, контракт —
из брифа ведущего (C6/C7-stop), план НЕ читался.

Самодостаточный файл (по образцу ``test_harness_no_orphans_acceptance.py``,
Task 1.4): дублирует ``HungChild``/``QuickChild``/снимок-хелперы, а не
импортирует ``multiprocess_framework/.../tests/_no_orphans_helpers.py``.
Небольшое дублирование принято сознательно (тот же прецедент).

Порты — ТОЛЬКО диапазон 9800-9899 (бронь 8860-8910 занята gui-service на время
разбора system.shutdown, см. docs/handoffs/2026-09-25_*).
"""

from __future__ import annotations

import os
import random
import signal
import socket
import sys
import time
from typing import Any, List, Optional

import pytest

from backend_ctl.harness import BackendHarness
from multiprocess_framework.modules.process_manager_module.launcher.system_launcher import SystemLauncher

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: SIGKILL/psutil semantics")

HUNG_CHILD_CLASS_PATH = "backend_ctl.tests.test_harness_parent_death_acceptance.HungChild"
QUICK_CHILD_CLASS_PATH = "backend_ctl.tests.test_harness_parent_death_acceptance.QuickChild"

_PORT_RANGE = (9800, 9899)


class HungChild:
    """Дублирует ``_no_orphans_helpers.HungChild`` (framework tests) — ребёнок,
    который НЕ уходит ни по ``stop_event``, ни по SIGTERM (SIG_IGN). Гарантирует,
    что снимок поддерева на момент SIGKILL PM ловит его ещё живым."""

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


class QuickChild:
    """Обычный процесс — baseline для C7 (без зависшего ребёнка, без эскалации)."""

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        return

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
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


def _alive_pids_zombie_aware(procs: List[Any]) -> List[int]:
    """C6: труп-зомби (не реапнутый НАМИ, т.к. мы не родитель этих внуков) считается
    «ушёл» — контракт прямо это оговаривает. ``is_running()`` у psutil про зомби
    отвечает True (запись в таблице процессов ещё есть), поэтому статус проверяется
    отдельно."""
    import psutil

    alive: List[int] = []
    for p in procs:
        try:
            if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                alive.append(p.pid)
        except Exception:  # noqa: BLE001
            pass
    return alive


def _wait_until_gone(
    procs: List[Any], deadline_s: float, poll_s: float = 0.05, zombie_aware: bool = False
) -> List[int]:
    checker = _alive_pids_zombie_aware if zombie_aware else _alive_pids
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        survivors = checker(procs)
        if not survivors:
            return []
        time.sleep(poll_s)
    return checker(procs)


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
    """Свободный порт СТРОГО в [9800, 9899) — 8860-8910 зарезервирован за
    gui-service (см. docstring модуля), общий ``_free_port()`` bind(0) диапазон
    не гарантирует."""
    lo, hi = _PORT_RANGE
    candidates = list(range(lo, hi))
    random.shuffle(candidates)
    for port in candidates:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"нет свободного порта в [{lo}, {hi})")


def _make_harness(class_path: str) -> BackendHarness:
    port = _free_port()

    def factory() -> SystemLauncher:
        return SystemLauncher(config={"child": {"class": class_path}}, stop_timeout=5.0)

    return BackendHarness(launcher_factory=factory, port=port, ready_timeout=20.0, teardown_timeout=10.0)


# ---------------------------------------------------------------------------
# C6 — kill -9 PM (харнес-стенд, порты 9800-9899): в пределах 2.0с ни один
# снятый на снимке ребёнок не жив (зомби считается ушедшим). Сегодня ожидается
# RED: у детей нет наблюдателя смерти родителя.
# ---------------------------------------------------------------------------


def test_kill9_pm_leaves_no_children():
    harness = _make_harness(HUNG_CHILD_CLASS_PATH)
    snap: List[Any] = []
    orch_pid: Optional[int] = None
    try:
        harness.start()
        orch_pid = harness._orch_pid  # white-box: тест именно о внутреннем pid harness'а
        assert orch_pid is not None, "harness.start() не выставил _orch_pid — окружение сломано"
        snap = _snapshot_children(orch_pid)
        assert snap, "снимок поддерева пуст ДО kill -9 — не удалось поймать ребёнка живым"

        os.kill(orch_pid, signal.SIGKILL)

        survivors = _wait_until_gone(snap, deadline_s=2.0, zombie_aware=True)
        assert survivors == [], f"дети PM пережили kill -9 PM дольше 2.0с (C6): {survivors}"
    finally:
        _cleanup_procs(snap)
        if orch_pid is not None:
            _kill_and_reap(orch_pid)
        try:
            harness.stop()
        except Exception:  # noqa: BLE001 — систему уже убили руками, stop() best-effort
            pass


# ---------------------------------------------------------------------------
# C7 (регресс, стоп-путь) — обычный harness.stop() (без зависшего ребёнка) не
# медленнее baseline'а. Baseline замерен на ЭТОМ дереве (pre-Task-1.5,
# скрипт-измеритель, не сам тест), 3 прогона: 1.178s / 1.175s / 1.180s (макс.
# 1.180с) → потолок 2.0с (запас ~0.82с, ~70% сверх худшего замера — та же
# логика, что framework A7: живая/CI-машина медленнее, но потолок не резиновый).
# ---------------------------------------------------------------------------


def test_harness_stop_time_not_worse():
    harness = _make_harness(QUICK_CHILD_CLASS_PATH)
    snap: List[Any] = []
    orch_pid: Optional[int] = None
    try:
        harness.start()
        orch_pid = harness._orch_pid
        assert orch_pid is not None, "harness.start() не выставил _orch_pid — окружение сломано"
        snap = _snapshot_children(orch_pid)

        start = time.monotonic()
        harness.stop()
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"harness.stop() занял {elapsed:.2f}с (ожидалось < 2.0с)"
    finally:
        _cleanup_procs(snap)
        if orch_pid is not None:
            _kill_and_reap(orch_pid)
