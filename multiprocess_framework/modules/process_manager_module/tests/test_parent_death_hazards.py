# -*- coding: utf-8 -*-
"""Hazard-тесты автора (Task 1.5, ADR-PMM-032): сторож смерти родителя в
``runner/process_runner.py``. Приёмка «ребёнок не переживает SIGKILL PM» — у
независимого тестера (``test_parent_death_acceptance.py``); здесь — места, где
ломается именно ЭТОТ механизм, как он построен:

1. Сторож взводится ТОЛЬКО при ``parent_pid`` (SRM-режим и сам PM не сторожатся):
   если по ошибке взводить от ``os.getppid()``, PM умирал бы вместе с launcher'ом —
   тихое расширение области (вне решения владельца).
2. Ветка «родитель жив, но не наш прямой родитель» (forkserver) — НЕ взводится:
   иначе цикл сразу видит ``getppid != parent_pid`` и убивает здорового ребёнка.
3. Ветка «родитель умер ДО старта сторожа» — выход, а не вечный сон: цикл в этом
   случае ничего не заметил бы (getppid уже равен init и не меняется).
4. На смерти: оба события взводятся ДО принудительного выхода; кооперативный
   ребёнок успевает уйти сам (код != _PARENT_DEATH_EXIT_CODE), зависший получает
   принудительный код. Сломать порядок → кооператив тоже уходит «насильно», без
   ``release_queues_at_exit``.

Смерть родителя в процессных тестах (4, 1) эмулируется подменой ``os.getppid``
ВНУТРИ ребёнка по multiprocessing-событию: ребёнок остаётся прямым ребёнком
pytest, и его ``exitcode`` наблюдаем (при настоящем SIGKILL реапит init и код
теряется). Настоящий SIGKILL — в приёмке тестера.

Всё, что может блокироваться, — с дедлайном; дети добиваются в finally.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import subprocess
import sys
import threading
import time
from typing import Any, List, Optional

import pytest

from ..runner import process_runner as pr
from ._no_orphans_helpers import HUNG_CHILD_CLASS_PATH, QUICK_CHILD_CLASS_PATH, kill_and_reap

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: getppid-сторож — no-op на Windows")


# ---------------------------------------------------------------------------
# In-process: ветки взведения _watch_parent (без реального os._exit).
# ---------------------------------------------------------------------------


class _Exited(Exception):
    pass


def _run_watch_in_thread(parent_pid: int, monkeypatch, deadline_s: float = 3.0, zero_grace: bool = True):
    """Запустить _watch_parent в daemon-потоке с подменённым os._exit (бросает _Exited).

    zero_grace=False — константа grace НЕ подменяется (тест меряет, что ветка её не ждёт).
    """
    exits: List[int] = []
    order: List[str] = []
    stop_evt, sys_evt = threading.Event(), threading.Event()

    class _SpyEvent:
        def __init__(self, evt: threading.Event, tag: str) -> None:
            self._evt, self._tag = evt, tag

        def set(self) -> None:
            order.append(self._tag)
            self._evt.set()

        def is_set(self) -> bool:
            return self._evt.is_set()

    def _fake_exit(code: int) -> None:
        order.append("exit")
        exits.append(code)
        raise _Exited()

    monkeypatch.setattr(pr.os, "_exit", _fake_exit)
    if zero_grace:
        monkeypatch.setattr(pr, "_PARENT_DEATH_GRACE_S", 0.0)

    def _body() -> None:
        try:
            pr._watch_parent(parent_pid, _SpyEvent(stop_evt, "stop"), _SpyEvent(sys_evt, "system"), "hz")
        except _Exited:
            pass

    t = threading.Thread(target=_body, daemon=True)
    t.start()
    t.join(timeout=deadline_s)
    return t, exits, order, stop_evt, sys_evt


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait(timeout=10.0)  # реапнут → pid свободен
    return p.pid


def test_not_direct_child_is_not_armed(monkeypatch):
    """parent_pid жив, но getppid() != parent_pid (forkserver) → ни выхода, ни событий."""
    # os.getpid() — живой процесс и НЕ родитель этого процесса.
    t, exits, order, stop_evt, sys_evt = _run_watch_in_thread(os.getpid(), monkeypatch, deadline_s=2.0)
    # Сторож обязан ВЕРНУТЬСЯ сразу (не крутить цикл): живой поток = взведён.
    assert not t.is_alive(), "сторож крутится при чужом живом parent_pid — взведён, где не должен"
    assert exits == [], f"ложный выход сторожа при живом не-прямом родителе: {exits}"
    assert not stop_evt.is_set() and not sys_evt.is_set(), f"события взведены ложно: {order}"


def test_parent_dead_before_watcher_start_exits(monkeypatch):
    """Родитель умер ДО старта сторожа (getppid уже init) → выход с кодом сторожа БЕЗ grace.

    Решение лида (C3): ребёнок ещё ничего не сделал, grace 1.5с здесь только съедает бюджет 2.0с.
    """
    dead = _dead_pid()
    t0 = time.monotonic()
    t, exits, order, stop_evt, sys_evt = _run_watch_in_thread(dead, monkeypatch, deadline_s=3.0, zero_grace=False)
    elapsed = time.monotonic() - t0
    assert not t.is_alive(), "сторож не вышел за 3с при заранее мёртвом родителе"
    assert exits == [75], f"ожидался os._exit(75), получено {exits}"
    # Литерал 0.5: grace 1.5 в этой ветке дал бы >= 1.5.
    assert elapsed < 0.5, f"ветка «умер до старта» ждала {elapsed:.2f}с — grace не снят"
    assert stop_evt.is_set() and sys_evt.is_set(), f"события не взведены до выхода: {order}"
    assert pr._PARENT_DEATH_EXIT_CODE == 75


def test_events_set_before_forced_exit(monkeypatch):
    """Порядок на смерти: stop_event и system_stop_event — ДО os._exit."""
    t, exits, order, _, _ = _run_watch_in_thread(_dead_pid(), monkeypatch, deadline_s=3.0)
    assert not t.is_alive()
    assert order == ["stop", "system", "exit"], f"порядок на смерти родителя: {order}"


def test_budget_arithmetic():
    """Опрос + grace укладываются в 2.0с приёмки с запасом на выход и реап."""
    assert pr._PARENT_POLL_S == 0.25 and pr._PARENT_DEATH_GRACE_S == 1.5
    assert pr._PARENT_POLL_S + pr._PARENT_DEATH_GRACE_S < 2.0


# ---------------------------------------------------------------------------
# Процессные: ребёнок = прямой ребёнок pytest, смерть родителя — подменой getppid.
# ---------------------------------------------------------------------------


def _child_entry(
    class_path: str, name: str, stop_event: Any, system_stop_event: Any, parent_pid: Optional[int], parent_dead: Any
) -> None:
    """Точка входа ребёнка: getppid «меняется» при parent_dead, затем обычный runner."""
    real = os.getppid
    os.getppid = lambda: 1 if parent_dead.is_set() else real()  # type: ignore[assignment]
    pr.run_process_function(class_path, name, stop_event, None, system_stop_event, parent_pid=parent_pid)


def _start_child(class_path: str, parent_pid: Optional[int]):
    ctx = mp.get_context()
    stop_evt, sys_evt, dead = ctx.Event(), ctx.Event(), ctx.Event()
    proc = ctx.Process(
        target=_child_entry,
        args=(class_path, "hz", stop_evt, sys_evt, parent_pid, dead),
        daemon=False,
    )
    proc.start()
    return proc, stop_evt, sys_evt, dead


def _settle(proc, s: float = 1.5) -> None:
    """Дать ребёнку пройти boot (spawn + импорты) до «смерти» родителя."""
    time.sleep(s)
    assert proc.is_alive(), f"ребёнок умер сам на boot (exitcode={proc.exitcode}) — окружение сломано"


@pytest.mark.timeout(30)
def test_cooperative_child_exits_itself_before_grace():
    """QuickChild уходит по взведённому stop_event сам — раньше grace, код != 75."""
    proc, stop_evt, sys_evt, dead = _start_child(QUICK_CHILD_CLASS_PATH, parent_pid=os.getpid())
    try:
        _settle(proc)
        t0 = time.monotonic()
        dead.set()
        proc.join(timeout=5.0)
        elapsed = time.monotonic() - t0
        assert not proc.is_alive(), "кооперативный ребёнок не вышел за 5с после смерти родителя"
        assert stop_evt.is_set() and sys_evt.is_set(), "сторож не взвёл оба события"
        assert proc.exitcode != pr._PARENT_DEATH_EXIT_CODE, (
            f"кооперативного ребёнка добил os._exit (код {proc.exitcode}), штатный выход не успел"
        )
        assert proc.exitcode == 0, f"кооперативный ребёнок вышел с кодом {proc.exitcode}"
        # Опрос 0.25 + штатный стоп; принудительный был бы >= 0.25 + 1.5.
        assert elapsed < 1.5, f"кооперативный выход занял {elapsed:.2f}с — не раньше grace"
    finally:
        if proc.is_alive():
            kill_and_reap(proc.pid)
        proc.join(timeout=5.0)


@pytest.mark.timeout(30)
def test_hung_child_gets_forced_exit_code():
    """HungChild игнорирует stop_event → принудительный os._exit(75) в пределах 2.0с."""
    # Ссылки на события держим: spawn-ребёнок пересобирает семафоры по имени, GC родителя их удалит.
    proc, _stop_evt, _sys_evt, dead = _start_child(HUNG_CHILD_CLASS_PATH, parent_pid=os.getpid())
    try:
        _settle(proc)
        t0 = time.monotonic()
        dead.set()
        proc.join(timeout=5.0)
        elapsed = time.monotonic() - t0
        assert not proc.is_alive(), "зависший ребёнок пережил смерть родителя на 5с"
        assert proc.exitcode == 75, f"ожидался код сторожа 75, получено {proc.exitcode}"
        assert elapsed < 2.0, f"принудительный выход занял {elapsed:.2f}с (бюджет 2.0с)"
    finally:
        if proc.is_alive():
            kill_and_reap(proc.pid)
        proc.join(timeout=5.0)


@pytest.mark.timeout(30)
def test_no_parent_pid_means_not_armed():
    """parent_pid=None (сам PM / SRM-режим) → смерть родителя НЕ гасит процесс."""
    proc, stop_evt, sys_evt, dead = _start_child(HUNG_CHILD_CLASS_PATH, parent_pid=None)
    try:
        _settle(proc)
        dead.set()
        time.sleep(2.5)  # > опрос + grace: взведённый сторож уже добил бы
        assert proc.is_alive(), f"процесс без parent_pid умер после «смерти» родителя (exitcode={proc.exitcode})"
        assert not stop_evt.is_set() and not sys_evt.is_set(), "события взведены без сторожа"
    finally:
        if proc.is_alive():
            kill_and_reap(proc.pid)
        proc.join(timeout=5.0)


# ---------------------------------------------------------------------------
# Смерть НАСТОЯЩЕГО родителя, пока ребёнок внутри initialize() (инъекция лида I6).
# Сторож стоит первой инструкцией run_process_function именно ради этого случая;
# дети-хелперы инициализируются мгновенно, и перенос сторожа к _run_lifecycle
# не ловил ни один тест. Эмуляция getppid здесь не годится — нужен реальный SIGKILL.
# ---------------------------------------------------------------------------

SLOW_INIT_CHILD_CLASS_PATH = f"{__name__}.SlowInitChild"
_MARKER_ENV = "PD_SLOW_INIT_MARKER"


class SlowInitChild:
    """initialize() блокирует ~10 с и не реагирует ни на события, ни на SIGTERM."""

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        self.name = name

    def initialize(self) -> bool:
        import signal

        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        with open(os.environ[_MARKER_ENV], "w") as f:  # «я внутри initialize()»
            f.write(str(os.getpid()))
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
        return True

    def run(self) -> None:
        while True:
            time.sleep(3600)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:  # pragma: no cover
        pass

    def shutdown(self) -> None:  # pragma: no cover
        pass


_SLOW_HOST_CODE = f"""
import json, time
from multiprocess_framework.modules.process_manager_module.core.process_registry import ProcessRegistry
reg = ProcessRegistry(logger=None)
p = reg.create_and_register("slow", {SLOW_INIT_CHILD_CLASS_PATH!r}, {{}}, "normal")
p.start()
print(json.dumps({{"child": p.pid}}), flush=True)
time.sleep(600)
"""


@pytest.mark.timeout(40)
def test_parent_sigkill_during_child_initialize(tmp_path):
    """SIGKILL родителя, пока ребёнок в initialize() → ребёнок исчез за 2.0 с."""
    import json
    import signal

    import psutil

    from ._no_orphans_helpers import wait_until_gone

    marker = tmp_path / "in_init"
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [os.getcwd(), env.get("PYTHONPATH", "")]))
    env[_MARKER_ENV] = str(marker)
    host = subprocess.Popen(
        [sys.executable, "-c", _SLOW_HOST_CODE], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env
    )
    child_pid: Optional[int] = None
    try:
        got: dict = {}
        reader = threading.Thread(target=lambda: got.update(json.loads(host.stdout.readline() or "{}")), daemon=True)
        reader.start()
        reader.join(timeout=20.0)
        child_pid = got.get("child")
        assert child_pid, "хост не сообщил pid ребёнка за 20с — окружение сломано"
        t_end = time.monotonic() + 20.0
        while not marker.exists() and time.monotonic() < t_end:
            time.sleep(0.02)
        assert marker.exists(), "ребёнок не вошёл в initialize() за 20с — окружение сломано"
        child = psutil.Process(child_pid)

        os.kill(host.pid, signal.SIGKILL)
        host.wait(timeout=5.0)

        survivors = wait_until_gone([child], deadline_s=2.0)
        assert survivors == [], f"ребёнок pid={child_pid} пережил SIGKILL родителя во время initialize() > 2.0с"
    finally:
        if host.poll() is None:
            host.kill()
            host.wait(timeout=5.0)
        kill_and_reap(child_pid)
