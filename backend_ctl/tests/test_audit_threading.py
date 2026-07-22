# -*- coding: utf-8 -*-
"""Task 2.2 — потокобезопасный и полный аудит-журнал.

Ultra-ревью 2026-07-20: ``AuditLog`` писался однопоточным (``self._seq += 1`` + append
в кольцо — не атомарная пара), а SDK гоняет ``tools/call`` в параллельных потоках
(``anyio.to_thread.run_sync`` + ``tg.start_soon``). Два системных пробела:

  * гонка на ``_seq``/кольце под конкурентными ``record()`` — дубли/пропуски номеров;
  * путь «бэкенд упал»: ``session.ensure()`` в :func:`dispatch_tool` бросал
    ``BackendUnavailable`` ДО веток аудита — попытка write/escalated-вызова к упавшему
    бэкенду не оставляла в журнале ни следа.

Этот файл бьёт по обоим — по ``audit.py`` напрямую (потокобезопасность) и через
``dispatch_tool`` (полнота на пути backend-down).
"""

from __future__ import annotations

import sys
import threading
from typing import Any, List

import pytest

from backend_ctl.audit import AuditLog
from backend_ctl.mcp_driver_session import DriverSession
from backend_ctl.mcp_errors import BackendUnavailable
from backend_ctl.dispatch import dispatch_tool


# --------------------------------------------------------------------------- #
#  Потокобезопасность record()/records()                                      #
# --------------------------------------------------------------------------- #


def test_concurrent_record_seq_is_strictly_monotonic(tmp_path) -> None:
    """N потоков x record() -> seq без дублей и пропусков.

    Гонка на ``self._seq += 1`` вероятностна: критическая секция — пара bytecode-
    инструкций, GIL редко переключается ровно в этом окне при обычном switch interval
    (5мс). Уменьшаем interval почти до нуля — эффективно превращаем eval-breaker
    в проверку "почти на каждой инструкции", иначе тест зеленел бы и на
    непотокобезопасном ``record()`` просто из-за редкости переключения контекста.
    """
    threads_n = 16
    per_thread = 150
    total = threads_n * per_thread
    # ring больше total: интересует полная последовательность seq, а не хвост кольца.
    log = AuditLog(path=str(tmp_path / "audit.jsonl"), ring=total + 10)

    barrier = threading.Barrier(threads_n)
    errors: List[BaseException] = []

    def _worker() -> None:
        try:
            barrier.wait()
            for i in range(per_thread):
                log.record("set_register", "write", {"i": i})
        except BaseException as exc:  # noqa: BLE001 — падение потока обязано валить тест
            errors.append(exc)

    original_interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        workers = [threading.Thread(target=_worker) for _ in range(threads_n)]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=30.0)
    finally:
        sys.setswitchinterval(original_interval)

    assert not [w for w in workers if w.is_alive()], "поток завис — вероятен дедлок на локе"
    assert not errors, f"поток упал: {errors[0]!r}"

    seqs = [e["seq"] for e in log.records()]
    assert len(seqs) == total, f"в кольце {len(seqs)} записей вместо {total} — потери при append"
    # Монотонность + отсутствие дублей + отсутствие пропусков — сплошная 1..N без дыр.
    assert seqs == list(range(1, total + 1)), "seq не монотонны / есть дубли или пропуски"


def test_records_negative_limit_returns_empty(tmp_path) -> None:
    """``records(limit=-1)`` -> [] (зеркало контракта ``limit=0``, не весь ринг)."""
    log = AuditLog(path=str(tmp_path / "audit.jsonl"))
    log.record("set_register", "write", {"i": 1})
    log.record("set_register", "write", {"i": 2})

    assert log.records(limit=-1) == []
    assert log.records(limit=0) == []
    assert len(log.records(limit=1)) == 1
    assert len(log.records()) == 2


# --------------------------------------------------------------------------- #
#  Полнота аудита на пути backend-down (dispatch_tool)                        #
# --------------------------------------------------------------------------- #


class _DeadFactory:
    """Фабрика driver'а, имитирующая упавший бэкенд: каждый вызов бросает BackendUnavailable."""

    def __call__(self) -> Any:
        raise BackendUnavailable("бэкенд не отвечает на 127.0.0.1:0")


@pytest.fixture
def isolated_record_dir(tmp_path, monkeypatch):
    """Каждый тест — свой каталог аудита (иначе файловый журнал делится между тестами)."""
    monkeypatch.setenv("BACKEND_CTL_RECORD_DIR", str(tmp_path / "records"))
    return tmp_path


def test_set_register_backend_down_is_audited_and_reraised(isolated_record_dir) -> None:
    """set_register при упавшем бэкенде -> в session_log запись попытки, исключение долетает.

    До фикса ``session.ensure()`` бросал BackendUnavailable ДО веток аудита в
    dispatch_tool — журнал доверия не видел самой попытки записи в упавший бэкенд.
    """
    session = DriverSession(driver_factory=_DeadFactory())

    with pytest.raises(BackendUnavailable):
        dispatch_tool(
            session,
            "set_register",
            {"process": "P", "register": "r", "field": "f", "value": 1},
        )

    log = session.read_audit()
    assert log["count"] == 1, "попытка write-инструмента к упавшему бэкенду не оставила следа в аудите"
    entry = log["entries"][-1]
    assert entry["tool"] == "set_register"
    assert entry["safety"] == "write"
    assert entry["ok"] is False
    assert "BackendUnavailable" in entry["error"], f"исход не отражает недоступность бэкенда: {entry}"


def test_send_command_backend_down_is_audited_and_reraised(isolated_record_dir) -> None:
    """Escalated-инструмент (send_command) — тот же контракт, что и write."""
    session = DriverSession(driver_factory=_DeadFactory())

    with pytest.raises(BackendUnavailable):
        dispatch_tool(session, "send_command", {"target": "Cam", "command": "ping", "args": {}})

    log = session.read_audit()
    assert log["count"] == 1
    entry = log["entries"][-1]
    assert entry["tool"] == "send_command"
    assert entry["safety"] == "escalated"
    assert entry["ok"] is False


def test_get_status_backend_down_still_raises_but_is_not_audited(isolated_record_dir) -> None:
    """Read-путь: BackendUnavailable по-прежнему долетает, но журнал доверия им не шумит.

    Аудит E.1 — только write/escalated (контракт задан ДО Task 2.2), backend-down на
    read-пути не должен внезапно начать засорять журнал.
    """
    session = DriverSession(driver_factory=_DeadFactory())

    with pytest.raises(BackendUnavailable):
        dispatch_tool(session, "get_status", {"process": "P"})

    assert session.read_audit()["count"] == 0
