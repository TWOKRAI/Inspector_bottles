"""Помощники spawn-процессов для акцептанса C-36.

Функции верхнего уровня: spawn пиклит цель по имени модуля. Замок осиротевает настоящим способом —
помощник берёт его и получает ``kill`` (Windows: ``TerminateProcess``, POSIX: ``SIGKILL``).
"""

from __future__ import annotations

import multiprocessing
import sys
import time
from queue import Empty
from typing import Any

# ``Process.exitcode`` после ``kill()``: Windows отдаёт -SIGTERM, POSIX -SIGKILL.
_KILLED_EXITCODE = -15 if sys.platform == "win32" else -9
_SPAWN_DEADLINE_S = 30.0


def _hold_read_lock(q: Any, conn: Any) -> None:
    q._rlock.acquire()
    conn.send("held")
    time.sleep(120)


def _hold_marker_event_lock(q: Any, conn: Any) -> None:
    q._reader_gone._cond.acquire()
    conn.send("held")
    time.sleep(120)


def _read_one(q: Any, conn: Any, timeout_s: float) -> None:
    try:
        conn.send(q.get(timeout=timeout_s))
    except Empty:
        conn.send(None)


def _kill_while_holding(target: Any, q: Any) -> None:
    """Запустить помощника, дождаться захвата замка и убить его, не дав отпустить."""
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=target, args=(q, child), daemon=True)
    proc.start()
    try:
        assert parent.poll(_SPAWN_DEADLINE_S), f"помощник не взял замок за {_SPAWN_DEADLINE_S} с"
        assert parent.recv() == "held"
    finally:
        proc.kill()
        proc.join(10.0)
    assert proc.exitcode == _KILLED_EXITCODE, f"помощник не убит: exitcode={proc.exitcode}"


def orphan_read_lock(q: Any) -> None:
    """Осиротить ``q._rlock``. Уже осиротевший замок повторно не берётся: помощник повис бы на ``acquire``."""
    if not q._rlock.acquire(False):
        return
    q._rlock.release()
    _kill_while_holding(_hold_read_lock, q)
    assert q._rlock.acquire(False) is False, "замок чтения не осиротел"


def orphan_marker_event_lock(q: Any) -> None:
    """Осиротить замок ``Event``-метки «читатель ушёл» очереди ``q``."""
    _kill_while_holding(_hold_marker_event_lock, q)
    assert q._reader_gone._cond.acquire(False) is False, "замок Event метки не осиротел"


def spawn_read(q: Any, get_timeout_s: float = 1.0) -> Any:
    """Прочитать одно сообщение из ``q`` в отдельном spawn-процессе. ``None`` — за ``get_timeout_s`` не пришло."""
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_read_one, args=(q, child, get_timeout_s), daemon=True)
    proc.start()
    try:
        assert parent.poll(_SPAWN_DEADLINE_S + get_timeout_s), "читатель не ответил за срок"
        return parent.recv()
    finally:
        proc.join(10.0)
        if proc.is_alive():
            proc.kill()
            proc.join(10.0)
