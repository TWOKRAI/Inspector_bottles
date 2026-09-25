# -*- coding: utf-8 -*-
"""Acceptance-тесты Task 1.5 (`lifecycle-stop-ownership`): «ребёнок, созданный
ProcessManager'ом, никогда не переживает его». Независимый тестер, контракт —
из брифа ведущего (C1-C7), план `plans/lifecycle-stop-ownership.md` НЕ читался.

«Родитель» = отдельный OS-хост-процесс (``_parent_death_helpers.py``, запущен
через ``python -m ... <сценарий>``), который строит ``ProcessRegistry`` +
``create_and_register`` + ``Process.start()`` — то же, чем PM спавнит детей на
старте/рестарте. Тест читает JSON-pid(ы) со stdout хоста, затем SIGKILL'ит
ИМЕННО ХОСТ (никогда не pytest), и поллит, пока снятый ребёнок не исчезнет.

Каждый тест сам ловит pid ребёнка ДО убийства и гарантированно добивает и
хост, и ребёнка в finally — эта машина не должна накопить сирот от RED-прогона.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from ._no_orphans_helpers import (
    QUICK_CHILD_CLASS_PATH,
    kill_and_reap,
    wait_until_gone,
)
from ..core.process_registry import ProcessRegistry

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: SIGKILL/psutil semantics")

_HOST_MODULE = "multiprocess_framework.modules.process_manager_module.tests._parent_death_helpers"
_REPO_ROOT = Path(__file__).resolve().parents[4]


# ---------------------------------------------------------------------------
# Хост-процесс: спавн + чтение JSON-строк с дедлайном (блокирующий readline —
# в отдельном daemon-потоке с join-дедлайном, TEST RULES: ничего не блокирует
# без потолка).
# ---------------------------------------------------------------------------


def _spawn_host(scenario: str) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    return subprocess.Popen(
        [sys.executable, "-m", _HOST_MODULE, scenario],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
    )


def _read_json_lines(proc: subprocess.Popen, count: int, deadline_s: float) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {"error": None}

    def _read() -> None:
        try:
            for _ in range(count):
                line = proc.stdout.readline()
                if not line:
                    result["error"] = "stdout хоста закрылся раньше ожидаемых строк"
                    return
                lines.append(json.loads(line))
        except Exception as exc:  # noqa: BLE001 — падение потока не должно висеть без дедлайна
            result["error"] = repr(exc)

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=deadline_s)
    if t.is_alive():
        pytest.fail(f"хост не напечатал {count} JSON-строк(и) за {deadline_s}с — подвисание, не целевой баг")
    if result["error"]:
        pytest.fail(f"не удалось прочитать вывод хоста: {result['error']}")
    return lines


def _kill_host(proc: subprocess.Popen) -> None:
    """SIGKILL хосту + реап (он — прямой ребёнок ЭТОГО процесса, не оставлять зомби)."""
    try:
        os.kill(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass  # best-effort — финальный cleanup в finally добьёт при необходимости


def _cleanup_host(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=5.0)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# C1 — обычный QuickChild переживает SIGKILL хоста сегодня (нет наблюдателя
# смерти родителя) → ожидается RED.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_child_exits_after_parent_sigkill():
    host = _spawn_host("single_quick")
    child_pid: Optional[int] = None
    try:
        [line] = _read_json_lines(host, 1, deadline_s=20.0)
        child_pid = line["child"]

        import psutil

        child = psutil.Process(child_pid)
        assert child.is_running(), "хост не поднял ребёнка живым до убийства — окружение сломано, не целевой баг"

        _kill_host(host)

        survivors = wait_until_gone([child], deadline_s=2.0)
        assert survivors == [], f"ребёнок pid={child_pid} пережил SIGKILL родителя (PM) дольше 2.0с (C1)"
    finally:
        _cleanup_host(host)
        if child_pid is not None:
            kill_and_reap(child_pid)


# ---------------------------------------------------------------------------
# C2 — то же самое, но ребёнок игнорирует и stop_event, и SIGTERM (HungChild) →
# ожидается RED (единственный способ его прибить — SIGKILL, которого сегодня
# никто не шлёт после смерти родителя).
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_hung_child_exits_after_parent_sigkill():
    host = _spawn_host("single_hung")
    child_pid: Optional[int] = None
    try:
        [line] = _read_json_lines(host, 1, deadline_s=20.0)
        child_pid = line["child"]

        import psutil

        child = psutil.Process(child_pid)
        assert child.is_running(), "хост не поднял ребёнка живым до убийства — окружение сломано, не целевой баг"

        _kill_host(host)

        survivors = wait_until_gone([child], deadline_s=2.0)
        assert survivors == [], f"зависший ребёнок pid={child_pid} пережил SIGKILL родителя дольше 2.0с (C2)"
    finally:
        _cleanup_host(host)
        if child_pid is not None:
            kill_and_reap(child_pid)


# ---------------------------------------------------------------------------
# C3 — родителя убивают СРАЗУ после того, как pid ребёнка стал наблюдаем (хост
# печатает pid без settle-окна, до вероятного завершения initialize()) →
# ожидается RED. Дедлайн 2.0с отсчитывается от момента наблюдения pid, а не от
# момента убийства.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_child_exits_when_parent_dies_during_boot():
    host = _spawn_host("boot_race")
    child_pid: Optional[int] = None
    try:
        [line] = _read_json_lines(host, 1, deadline_s=20.0)
        observed_at = time.monotonic()
        child_pid = line["child"]

        import psutil

        child = psutil.Process(child_pid)

        _kill_host(host)

        remaining = 2.0 - (time.monotonic() - observed_at)
        assert remaining > 0, "чтение pid + kill заняли больше 2.0с сами по себе — окружение сломано"
        survivors = wait_until_gone([child], deadline_s=remaining)
        assert survivors == [], (
            f"ребёнок pid={child_pid} пережил гибель родителя во время своего boot дольше 2.0с "
            f"от момента наблюдения pid (C3)"
        )
    finally:
        _cleanup_host(host)
        if child_pid is not None:
            kill_and_reap(child_pid)


# ---------------------------------------------------------------------------
# C4a — родитель ЖИВ → дети живут >= 5с (нет ложных срабатываний watchdog'а).
# Сегодня GREEN: ничего не трогает детей, пока хост жив.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_children_stay_alive_while_parent_alive():
    host = _spawn_host("alive_pair")
    pids: List[int] = []
    try:
        [line] = _read_json_lines(host, 1, deadline_s=20.0)
        pids = [line["a"], line["b"]]

        import psutil

        children = [psutil.Process(p) for p in pids]
        assert all(c.is_running() for c in children), "хост не поднял пару живой — окружение сломано, не целевой баг"

        # >= 5с литерал из контракта C4; +0.2с запас против таймингов планировщика ОС.
        time.sleep(5.2)

        assert host.poll() is None, "хост неожиданно умер сам — не целевой баг для этой проверки"
        dead = [c.pid for c in children if not c.is_running()]
        assert dead == [], f"дети {dead} умерли, хотя родитель жив >= 5с (C4, ложное срабатывание)"
    finally:
        _cleanup_host(host)
        for pid in pids:
            kill_and_reap(pid)


# ---------------------------------------------------------------------------
# C4b — ребёнок, запущенный из короткоживущего потока родителя, переживает
# выход ЭТОГО потока (поток — не владелец процесса, владелец — сам хост).
# Сегодня GREEN.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_child_started_from_short_lived_thread_survives():
    host = _spawn_host("thread_child")
    child_pid: Optional[int] = None
    try:
        [line] = _read_json_lines(host, 1, deadline_s=20.0)
        assert line.get("thread_done") is True, f"хост не подтвердил выход потока-спавнера: {line}"
        child_pid = line["child"]
        assert child_pid is not None, "хост не сообщил pid ребёнка — окружение сломано, не целевой баг"

        import psutil

        child = psutil.Process(child_pid)
        assert child.is_running(), "ребёнок не поднялся живым — окружение сломано, не целевой баг"

        # >= 3с литерал из контракта C4 (после выхода потока-спавнера); +0.2с запас.
        time.sleep(3.2)

        assert host.poll() is None, "хост неожиданно умер сам — не целевой баг для этой проверки"
        assert child.is_running(), f"ребёнок pid={child_pid} умер после выхода спавнившего его потока (C4)"
    finally:
        _cleanup_host(host)
        if child_pid is not None:
            kill_and_reap(child_pid)


# ---------------------------------------------------------------------------
# C4c — процесс, остановленный и пересозданный под тем же именем
# (stop -> remove -> create_and_register -> start), остаётся жив. Контракт не
# даёт числового порога для ЭТОГО подслучая (только «остаётся жив») — берём
# тот же порядок величины, что C4b (2.0с), с явной оговоркой в отчёте.
# Сегодня GREEN.
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_restarted_child_survives():
    host = _spawn_host("restarted_child")
    old_pid: Optional[int] = None
    new_pid: Optional[int] = None
    try:
        first, second = _read_json_lines(host, 2, deadline_s=20.0)
        assert first["phase"] == "first" and second["phase"] == "second", (first, second)
        old_pid, new_pid = first["child"], second["child"]
        assert new_pid != old_pid, "пересоздание вернуло тот же pid — не воплощение переспавнилось"

        import psutil

        new_child = psutil.Process(new_pid)
        assert new_child.is_running(), "пересозданный ребёнок не поднялся живым — окружение сломано"

        time.sleep(2.0)

        assert host.poll() is None, "хост неожиданно умер сам — не целевой баг для этой проверки"
        assert new_child.is_running(), f"пересозданный ребёнок pid={new_pid} умер сам по себе (C4, false positive)"
    finally:
        _cleanup_host(host)
        for pid in (old_pid, new_pid):
            if pid is not None:
                kill_and_reap(pid)


# ---------------------------------------------------------------------------
# C7 (регресс) — рестарт ОДНОГО процесса (stop_one -> remove_process ->
# create_and_register -> start) не медленнее baseline'а. In-process (не через
# host-хелпер) — измеряется сама операция ProcessRegistry, а не факт гибели
# родителя. Baseline замерен на ЭТОМ дереве (pre-Task-1.5, скрипт-измеритель,
# не сам тест), 5 прогонов: 0.434s / 0.448s / 0.441s / 0.431s / 0.446s
# (макс. 0.448с) → потолок 1.0с (запас ~2.2x худшего замера; QuickChild уходит
# по stop_event мгновенно, полная эскалация terminate/kill сюда не попадает —
# запас держит живую/CI-машину медленнее ноутбука тестера).
# ---------------------------------------------------------------------------


@pytest.mark.timeout(30)
def test_restart_time_not_worse():
    registry = ProcessRegistry(logger=None)
    first = registry.create_and_register("r", QUICK_CHILD_CLASS_PATH, {}, "normal")
    assert first is not None
    first.start()
    second = None
    try:
        start = time.monotonic()
        stopped = registry.stop_one("r", timeout=5.0)
        registry.remove_process("r")
        second = registry.create_and_register("r", QUICK_CHILD_CLASS_PATH, {}, "normal")
        assert second is not None
        second.start()
        elapsed = time.monotonic() - start

        assert stopped is True, "stop_one('r') не подтвердил смерть первого воплощения"
        assert elapsed < 1.0, f"рестарт одного процесса занял {elapsed:.3f}с (ожидалось < 1.0с, baseline ~0.1с)"
    finally:
        registry.stop_one("r", timeout=5.0)
        if second is not None and second.pid is not None:
            kill_and_reap(second.pid)
        if first.pid is not None:
            kill_and_reap(first.pid)
