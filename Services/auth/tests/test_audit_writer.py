# -*- coding: utf-8 -*-
"""
Тесты AuditWriter — фоновый поток + батчинг + JSONL fallback + recover.

Все тесты используют in-memory SQLite и tmp_path (без сетевых вызовов).
"""
from __future__ import annotations

import json
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from Services.auth.audit_writer import AuditWriter
from Services.auth.models import AuditEntry
from Services.auth.storage.audit_storage import SqliteAuditStorage


# =============================================================================
# Вспомогательные фабрики
# =============================================================================


def _make_storage() -> SqliteAuditStorage:
    """Создать in-memory хранилище со схемой."""
    storage = SqliteAuditStorage("sqlite:///:memory:")
    storage.ensure_schema()
    return storage


def _make_entry(action_type: str = "field_update") -> AuditEntry:
    """Создать тестовую AuditEntry с уникальным entry_id."""
    return AuditEntry.with_truncation(
        entry_id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        user_id="uid-test",
        username="testuser",
        action_type=action_type,
        resource="test.field",
    )


# =============================================================================
# Тесты
# =============================================================================


def test_log_and_flush(tmp_path: Path) -> None:
    """log() → start/stop → записи в storage."""
    storage = _make_storage()
    writer = AuditWriter(storage, fallback_path=str(tmp_path / "fallback.jsonl"))
    writer.start()

    entries = [_make_entry() for _ in range(5)]
    for e in entries:
        writer.log(e)

    writer.stop()

    # Все 5 записей должны быть в БД
    results = storage.list_audit()
    assert len(results) == 5

    stored_ids = {r.entry_id for r in results}
    for e in entries:
        assert e.entry_id in stored_ids


def test_fallback_on_storage_error(tmp_path: Path) -> None:
    """При сбое storage.append_audit → запись попадает в JSONL fallback."""
    storage = _make_storage()
    fallback = tmp_path / "fallback.jsonl"
    writer = AuditWriter(storage, fallback_path=str(fallback))

    # Сломаем хранилище — monkeypatch через замену метода
    def broken_append_audit(entry: AuditEntry) -> None:
        raise RuntimeError("Симулированный сбой SQLite")

    storage.append_audit = broken_append_audit  # type: ignore[method-assign]

    writer.start()
    entry = _make_entry()
    writer.log(entry)
    writer.stop()

    # JSONL файл должен существовать и содержать запись
    assert fallback.exists(), "JSONL fallback файл не создан"
    lines = [l for l in fallback.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 1

    data = json.loads(lines[0])
    assert data["entry_id"] == entry.entry_id


def test_recover_fallback(tmp_path: Path) -> None:
    """JSONL существует → recover_fallback() → записи в БД, файл архивирован."""
    storage = _make_storage()
    fallback = tmp_path / "fallback.jsonl"

    # Создаём JSONL с 3 записями вручную
    entries = [_make_entry() for _ in range(3)]
    with open(fallback, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(e.model_dump_json() + "\n")

    writer = AuditWriter(storage, fallback_path=str(fallback))
    count = writer.recover_fallback()

    assert count == 3, f"Ожидалось 3 восстановленных записи, получено {count}"

    # Записи в БД
    results = storage.list_audit()
    assert len(results) == 3

    # Исходный JSONL-файл переименован
    assert not fallback.exists(), "Исходный fallback-файл не был архивирован"
    migrated_files = list(tmp_path.glob("fallback.jsonl.migrated.*"))
    assert len(migrated_files) == 1, "Архивный файл не найден"


def test_concurrent_writes(tmp_path: Path) -> None:
    """5 потоков × 20 записей = ровно 100 записей в БД после stop()."""
    storage = _make_storage()
    writer = AuditWriter(storage, fallback_path=str(tmp_path / "fallback.jsonl"))
    writer.start()

    n_threads = 5
    n_per_thread = 20
    barrier = threading.Barrier(n_threads)

    def write_entries() -> None:
        barrier.wait()  # Стартуем все потоки одновременно
        for _ in range(n_per_thread):
            writer.log(_make_entry())

    threads = [threading.Thread(target=write_entries) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    writer.stop()

    results = storage.list_audit()
    assert len(results) == n_threads * n_per_thread, (
        f"Ожидалось {n_threads * n_per_thread} записей, получено {len(results)}"
    )


def test_stop_flush(tmp_path: Path) -> None:
    """После stop() все записи из очереди должны быть записаны в storage."""
    storage = _make_storage()
    writer = AuditWriter(storage, fallback_path=str(tmp_path / "fallback.jsonl"))
    writer.start()

    n = 30
    entries = [_make_entry() for _ in range(n)]
    for e in entries:
        writer.log(e)

    # Останавливаем немедленно — flush должен произойти в потоке
    writer.stop()

    results = storage.list_audit()
    assert len(results) == n, (
        f"После stop() ожидалось {n} записей в БД, получено {len(results)}"
    )
