# -*- coding: utf-8 -*-
"""Хелперы для acceptance-тестов Task 1.4 (`lifecycle-stop-ownership`, план НЕ читался —
контракт задан в брифе тестера).

Не production-код (это тестовая утилита, НЕ dev/module-contract) — но REDS ссылаются
на классы отсюда по dotted-path, поэтому все классы процессов — на верхнем уровне
модуля (``run_process_function`` грузит их через ``importlib``, не пиклит объекты).

Содержит:
    * ``HungChild`` — дочерний процесс, который игнорирует И ``stop_event``, И SIGTERM
      (SIG_IGN внутри ``run()``); убить можно только SIGKILL. Это тестовый двойник
      «зависшего ребёнка» из живого факта (4 процесса с PPID 1 висели ~8.5ч).
    * ``QuickChild`` — обычный процесс: ``run()`` возвращается сразу, дальше
      ``_run_lifecycle`` (process_runner) опрашивает stop_event каждые 0.1с. Baseline
      для A7 (нет регрессии).
    * pid-снимок/уборка: ``snapshot_children`` / ``alive_pids`` / ``kill_and_reap``.
"""

from __future__ import annotations

import signal
import time
from typing import Any, List, Optional

HUNG_CHILD_CLASS_PATH = "multiprocess_framework.modules.process_manager_module.tests._no_orphans_helpers.HungChild"
QUICK_CHILD_CLASS_PATH = "multiprocess_framework.modules.process_manager_module.tests._no_orphans_helpers.QuickChild"


class HungChild:
    """Дочерний процесс, который НЕ уходит ни по ``stop_event``, ни по SIGTERM.

    ``run()`` НИКОГДА не возвращается — поэтому poll-цикл ``_run_lifecycle``
    (process_runner.py), который проверяет ``stop_event``/``system_stop_event``/
    ``should_stop()``, вообще не достигается: игнорирование stop-сигналов полное,
    не частичное. SIGTERM игнорируется явным ``SIG_IGN`` (spawn-контекст: свежий
    интерпретатор, диспозиции сигналов по умолчанию — без этого процесс упал бы
    от дефолтного SIGTERM). Единственный способ прибить — SIGKILL (`process.kill()`
    у multiprocessing, либо ``killpg`` с SIGKILL).
    """

    def __init__(self, name: str, shared_resources: Any, config: Any) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        # SIG_IGN ДО входа в бесконечный сон — иначе окно между spawn и этой строкой
        # (доли мс) оставило бы SIGTERM смертельным по дефолтной диспозиции.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(3600)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:  # pragma: no cover — run() никогда не возвращается сюда
        pass

    def shutdown(self) -> None:  # pragma: no cover
        pass


class QuickChild:
    """Обычный процесс: ``run()`` возвращается сразу, штатно уходит по stop_event.

    Baseline для A7 — измеряет НЕ-регрессию обычного стопа (без зависшего ребёнка).
    """

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


# ---------------------------------------------------------------------------
# pid-снимок / уборка — identity по create_time (psutil.Process кэширует его и
# сверяет в is_running(), так что PID-реюз не даёт ложных "жив").
# ---------------------------------------------------------------------------


def snapshot_children(orchestrator_pid: int) -> List[Any]:
    """Снимок ЖИВОГО поддерева оркестратора (psutil.Process, recursive) — ДО убийства.

    Best-effort: если psutil недоступен/оркестратор уже мёртв — пустой список
    (вызывающий тест должен считать это неудачей ЛОВА снимка, а не свойства).
    """
    try:
        import psutil

        return psutil.Process(orchestrator_pid).children(recursive=True)
    except Exception:  # noqa: BLE001 — снимок не критичен для остальной части теста
        return []


def alive_pids(procs: List[Any]) -> List[int]:
    """Из снимка — те, что всё ещё реально живы (identity по create_time)."""
    alive: List[int] = []
    for p in procs:
        try:
            if p.is_running():
                alive.append(p.pid)
        except Exception:  # noqa: BLE001
            pass
    return alive


def wait_until_gone(procs: List[Any], deadline_s: float, poll_s: float = 0.05) -> List[int]:
    """Опросить снимок до дедлайна; вернуть pid'ы, всё ещё живые к его истечению."""
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        survivors = alive_pids(procs)
        if not survivors:
            return []
        time.sleep(poll_s)
    return alive_pids(procs)


def kill_and_reap(pid: Optional[int]) -> None:
    """SIGKILL по pid + короткое ожидание. Best-effort, для teardown тестов."""
    if pid is None:
        return
    try:
        import os

        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        import psutil

        p = psutil.Process(pid)
        p.wait(timeout=2.0)
    except Exception:  # noqa: BLE001
        pass


def cleanup_procs(procs: List[Any]) -> None:
    """SIGKILL всех ещё живых psutil.Process из снимка (teardown)."""
    for p in procs:
        try:
            if p.is_running():
                kill_and_reap(p.pid)
        except Exception:  # noqa: BLE001
            pass


def free_port() -> int:
    """Свободный TCP-порт (best-effort: bind(0) → close → вернуть номер)."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
