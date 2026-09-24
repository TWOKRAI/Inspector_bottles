# -*- coding: utf-8 -*-
"""Acceptance-тесты Task 1.4 (`lifecycle-stop-ownership`): «ни один путь остановки
не оставляет процессов-сирот». Независимый тестер, контракт — из брифа/handoff,
план НЕ читался. Источник свойств — прочитанный код (see docs/handoffs/2026-09-24_
task-1.4-tester.md), сами тесты пишутся и запускаются в этом файле впервые.

Каждый тест сам ловит снимок живого поддерева ДО остановки и гарантированно
добивает всё в finally — эта машина не должна накопить сирот от RED-прогона.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ._no_orphans_helpers import (
    HUNG_CHILD_CLASS_PATH,
    QUICK_CHILD_CLASS_PATH,
    alive_pids,
    cleanup_procs,
    kill_and_reap,
    snapshot_children,
    wait_until_gone,
)
from ..launcher.process_tree_guard import ProcessTreeGuard
from ..launcher.system_launcher import SystemLauncher

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: setsid/killpg/SIGKILL semantics")


# ---------------------------------------------------------------------------
# A2 — spawner/launcher stop с зависшим ребёнком: 0 живых, никто не ушёл к PID 1.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_spawner_leaves_no_orphan_with_hung_child():
    launcher = SystemLauncher(config={"hung": {"class": HUNG_CHILD_CLASS_PATH}}, stop_timeout=5.0)
    snap = []
    pm_process = None
    try:
        launcher.start()
        assert launcher.wait_until_ready(20.0), "PM не стал ready за 20с — окружение сломано, не целевой баг"
        pm_process = launcher._spawner.get_process()
        snap = snapshot_children(pm_process.pid)
        assert snap, "снимок поддерева пуст ДО остановки — не удалось поймать зависшего ребёнка живым"

        launcher.stop()

        survivors = wait_until_gone(snap, deadline_s=3.0)
        assert survivors == [], f"остались живые PID после launcher.stop(): {survivors}"

        # Второй assert для ясности сообщения, недостижим если первый уже упал
        for p in snap:
            try:
                if p.is_running():
                    assert p.ppid() != 1, f"pid {p.pid} унаследован PID 1 — реальный сирота"
            except Exception:  # noqa: BLE001
                pass
    finally:
        cleanup_procs(snap)
        if pm_process is not None and pm_process.is_alive():
            kill_and_reap(pm_process.pid)


# ---------------------------------------------------------------------------
# A3 — ProcessTreeGuard.kill_tree() после того, как лидер группы уже reaped,
# всё равно валит живого члена группы (POSIX group fallback).
# ---------------------------------------------------------------------------


_GRANDCHILD_SLEEP = "import time; time.sleep(60)"
_LEADER_SCRIPT = (
    "import subprocess, sys, time;"
    "p = subprocess.Popen([sys.executable, '-c', " + repr(_GRANDCHILD_SLEEP) + "]);"
    "print(p.pid, flush=True);"
    "time.sleep(0.3);"
    "sys.exit(0)"
)


@pytest.mark.timeout(30)
def test_guard_kills_group_member_after_leader_reaped():
    import psutil

    leader = subprocess.Popen(
        [sys.executable, "-c", _LEADER_SCRIPT],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    member = None
    try:
        line = leader.stdout.readline()
        child_pid = int(line.strip())
        member = psutil.Process(child_pid)
        assert member.is_running(), "внук не поднялся живым — окружение сломано, не целевой баг"

        leader.wait(timeout=5)  # реапаем лидера НА САМОМ ДЕЛЕ — pid уходит из таблицы процессов

        guard = ProcessTreeGuard()
        guard.adopt(leader.pid)
        guard.kill_tree([member])

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and member.is_running():
            time.sleep(0.05)

        assert not member.is_running(), (
            f"член группы pid={child_pid} пережил kill_tree() после реапнутого лидера — "
            "os.getpgid(leader.pid) поднял ProcessLookupError, guard посчитал это 'killed=True' "
            "и пропустил psutil-fallback, хотя [member] был передан явно"
        )
    finally:
        if member is not None:
            kill_and_reap(member.pid)
        if leader.poll() is None:
            kill_and_reap(leader.pid)


# ---------------------------------------------------------------------------
# A4a/A4b — PM успевает завершить свою эскалацию (5.0+1.0+1.0=7.0s) раньше,
# чем внешний spawner-таймаут (по умолчанию 5.0s) успевает его перебить.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(60)
def test_pm_completes_own_escalation_before_spawner_would_intervene():
    launcher = SystemLauncher(config={"hung": {"class": HUNG_CHILD_CLASS_PATH}}, stop_timeout=5.0)
    snap = []
    pm_process = None
    try:
        launcher.start()
        assert launcher.wait_until_ready(20.0), "PM не стал ready за 20с — окружение сломано, не целевой баг"
        pm_process = launcher._spawner.get_process()
        snap = snapshot_children(pm_process.pid)
        assert pm_process.exitcode is None, "exitcode не None ДО stop() — PM уже мёртв, окружение сломано"

        launcher.stop()

        assert pm_process.exitcode == 0, (
            f"PM exitcode={pm_process.exitcode!r} (ожидался 0 — чистый самостоятельный выход после "
            "своей эскалации 5.0+1.0+1.0=7.0с). Отрицательный exitcode значит, что spawner сигналил "
            "PM раньше, чем тот сам разобрался с зависшим ребёнком."
        )
    finally:
        cleanup_procs(snap)
        if pm_process is not None and pm_process.is_alive():
            kill_and_reap(pm_process.pid)


@pytest.mark.timeout(60)
def test_outer_wait_survives_past_inner_escalation_budget_6_5s():
    launcher = SystemLauncher(config={"hung": {"class": HUNG_CHILD_CLASS_PATH}}, stop_timeout=5.0)
    snap = []
    pm_process = None
    try:
        launcher.start()
        assert launcher.wait_until_ready(20.0), "PM не стал ready за 20с — окружение сломано, не целевой баг"
        pm_process = launcher._spawner.get_process()
        snap = snapshot_children(pm_process.pid)

        t = threading.Thread(target=launcher.stop, daemon=True)
        t.start()
        time.sleep(6.5)
        alive_at_6_5 = pm_process.is_alive()
        t.join(timeout=15.0)
        assert not t.is_alive(), "launcher.stop() не завершился за 15с после отметки 6.5с — подвисание"

        assert alive_at_6_5, (
            "PM мёртв уже к отметке t=6.5с (строго между внешним таймаутом spawner'а 5.0с и "
            "внутренним бюджетом PM 7.0с) — значит внешний spawner прервал PM ДО того, как тот "
            "закончил собственную эскалацию по зависшему ребёнку"
        )
    finally:
        cleanup_procs(snap)
        if pm_process is not None and pm_process.is_alive():
            kill_and_reap(pm_process.pid)


# ---------------------------------------------------------------------------
# A6 — SIGINT реальному OS-процессу лаунчера (не .stop() напрямую) с зависшим
# ребёнком: 0 живых после выхода.
# ---------------------------------------------------------------------------

_SIGINT_MAIN_SCRIPT = """
import sys, time, threading
from multiprocess_framework.modules.process_manager_module.launcher.spawner import ProcessSpawner
from multiprocess_framework.modules.process_manager_module.tests._no_orphans_helpers import (
    HUNG_CHILD_CLASS_PATH, snapshot_children,
)

def _main():
    spawner = ProcessSpawner(processes_config={"hung": {"class": HUNG_CHILD_CLASS_PATH}}, stop_timeout=5.0)
    spawner.launch_orchestrator()
    proc = spawner.get_process()
    time.sleep(2.0)  # дать PM's initialize() заспавнить зависшего ребёнка
    children = snapshot_children(proc.pid)
    print(children[0].pid if children else -1, flush=True)

    done = threading.Event()
    _orig_stop = spawner.stop
    def _stop(*a, **kw):
        try:
            _orig_stop(*a, **kw)
        finally:
            done.set()
    spawner.stop = _stop  # instance-attribute shadowing: _signal_handler зовёт self.stop()

    done.wait(timeout=30.0)
    sys.exit(0)


if __name__ == "__main__":
    # multiprocessing (spawn context) перечитывает __main__ файл в каждом дочернем
    # интерпретаторе — без этой обвязки launch_orchestrator() падает RuntimeError
    # "An attempt has been made to start a new process before the current process
    # has finished its bootstrapping phase" (реально воспроизведено этим прогоном).
    _main()
"""


def _run_sigint_main_blocking(env, script_path, result):
    proc = subprocess.Popen(
        [sys.executable, str(script_path)],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    result["proc"] = proc
    try:
        line = proc.stdout.readline()
        result["hung_pid"] = int(line.strip())
    except Exception as exc:  # noqa: BLE001
        result["read_error"] = exc
        return
    result["read_done"] = True
    # SIGINT только после того, как pid прочитан
    os.kill(proc.pid, signal.SIGINT)
    try:
        proc.wait(timeout=25.0)
        result["returncode"] = proc.returncode
    except subprocess.TimeoutExpired:
        # Не хаваем как "не целевой баг" — просто не даём необработанному исключению
        # уронить поток без join'а (TEST RULES: любой блокирующий вызов — с дедлайном).
        result["wait_timeout"] = True


@pytest.mark.timeout(60)
def test_sigint_to_main_pid_leaves_no_orphan(tmp_path):
    script = tmp_path / "sigint_main.py"
    script.write_text(_SIGINT_MAIN_SCRIPT)

    repo_root = Path(__file__).resolve().parents[4]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)

    result: dict = {}
    t = threading.Thread(target=_run_sigint_main_blocking, args=(env, script, result), daemon=True)
    t.start()
    t.join(timeout=40.0)

    member = None
    try:
        if "read_error" in result:
            pytest.fail(f"не удалось прочитать pid зависшего ребёнка из подпроцесса: {result['read_error']!r}")
        if not result.get("read_done"):
            proc = result.get("proc")
            if proc is not None:
                proc.kill()
            pytest.fail("подпроцесс не напечатал pid ребёнка за 40с — окружение сломано, не целевой баг")

        hung_pid = result["hung_pid"]
        assert hung_pid != -1, "PM не заспавнил зависшего ребёнка за 2с — окружение сломано, не целевой баг"

        import psutil

        member = psutil.Process(hung_pid)

        if t.is_alive():
            proc = result.get("proc")
            if proc is not None:
                proc.kill()
            pytest.fail("подпроцесс не завершился за 25с после SIGINT — подвисание вместо падения")

        survivors = wait_until_gone([member], deadline_s=3.0)
        assert survivors == [], f"зависший ребёнок pid={hung_pid} пережил SIGINT главному pid лаунчера: {survivors}"
    finally:
        if member is not None:
            kill_and_reap(member.pid)
        proc = result.get("proc")
        if proc is not None and proc.poll() is None:
            proc.kill()


# ---------------------------------------------------------------------------
# A7 (ожидается GREEN) — обычный stop без зависшего ребёнка не медленнее
# baseline'а более чем на 0.5с (литерал < 2.0с).
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_normal_stop_without_hung_child_is_not_slower():
    launcher = SystemLauncher(config={"quick": {"class": QUICK_CHILD_CLASS_PATH}}, stop_timeout=5.0)
    snap = []
    pm_process = None
    try:
        launcher.start()
        assert launcher.wait_until_ready(20.0), "PM не стал ready за 20с — окружение сломано, не целевой баг"
        pm_process = launcher._spawner.get_process()
        snap = snapshot_children(pm_process.pid)

        start = time.monotonic()
        launcher.stop()
        elapsed = time.monotonic() - start

        assert elapsed < 2.0, f"обычный stop() занял {elapsed:.2f}с (ожидалось < 2.0с)"
    finally:
        cleanup_procs(snap)
        if pm_process is not None and pm_process.is_alive():
            kill_and_reap(pm_process.pid)
