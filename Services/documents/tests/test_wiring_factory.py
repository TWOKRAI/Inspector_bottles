# -*- coding: utf-8 -*-
"""Независимые тесты фабрики стока документов (Ф8.5, приёмка A).

Пишутся ТОЛЬКО по приёмочным критериям задачи, без чтения ``Services/documents/wiring.py``
— поэтому стенд трактует ``make_document_sink`` как чёрный ящик: вызывающий знает только
форму ``config`` (``db_path``, ``retention_sec``, ``purge_interval_sec``, ``busy_timeout_sec``)
и то, что результат обязан удовлетворять ``append(dict) -> bool`` (плюс, по контракту
``Services.documents.interfaces.IDocumentStore``, читаться через ``query``/``purge_expired``
— пакет уже объявляет фабрику продолжением этого контракта, а не новым).

Файловая БД (``tmp_path``), не in-memory: WAL-проверка требует настоящего файла на диске
(``BaseSyncAdapter`` берёт новое соединение на каждый вызов, и ``:memory:`` не переживает
между ними). Каждый созданный сток закрывается явно — иначе на Windows уборка ``tmp_path``
падает не там, где ошибся тест.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from Services.documents import KIND_AUDIT, KIND_VERDICT

FACTORY = "Services.documents.wiring:make_document_sink"


def _import_factory():
    """Импортировать ``make_document_sink`` по адресу ``модуль:атрибут`` из приёмки.

    Явный импорт (не через ``wire_document_sink``) — часть A приёмки касается САМОЙ
    фабрики, изолированно от сшивки в процесс (часть B).
    """
    module_path, _, attr = FACTORY.partition(":")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, attr)


make_document_sink = _import_factory()


def _close(sink) -> None:
    close = getattr(sink, "close", None)
    if callable(close):
        close()


class TestFactoryWritesAndReads:
    def test_appended_document_is_readable_back(self, tmp_path) -> None:
        db_path = tmp_path / "docs.db"
        sink = make_document_sink({"db_path": str(db_path)})
        try:
            ok = sink.append({"kind": KIND_AUDIT, "ts": time.time(), "summary": "session_set log_level=DEBUG"})

            assert ok is True
            found = sink.query(kind=KIND_AUDIT)
            assert len(found) == 1
            assert found[0]["summary"] == "session_set log_level=DEBUG"
        finally:
            _close(sink)


class TestFactoryEnablesWAL:
    def test_journal_mode_is_really_wal_on_disk(self, tmp_path) -> None:
        """PRAGMA journal_mode проверяется ПОСТОРОННИМ соединением к настоящему файлу.

        In-memory БД здесь не годится вовсе: у sqlite каждое соединение к ``:memory:`` —
        отдельная база, а адаптер берёт новое соединение на каждый вызов — WAL, заданный
        на "своём" соединении, не был бы виден снаружи никогда.
        """
        db_path = tmp_path / "wal.db"
        sink = make_document_sink({"db_path": str(db_path)})
        try:
            # Хотя бы одна запись — таблица и файл должны существовать на диске.
            sink.append({"kind": KIND_AUDIT, "ts": time.time(), "summary": "boot"})
        finally:
            _close(sink)

        assert db_path.exists(), "фабрика обязана создать настоящий файл БД"
        conn = sqlite3.connect(str(db_path))
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        finally:
            conn.close()
        assert str(mode).lower() == "wal"


class TestRetentionOnlyAppliesToDeclaredKinds:
    def test_kind_without_ttl_is_never_purged(self, tmp_path) -> None:
        """Post ``purge_expired``: род без срока не удаляется НИКОГДА (interfaces.py)."""
        db_path = tmp_path / "retention.db"
        sink = make_document_sink(
            {
                "db_path": str(db_path),
                # Срок задан ТОЛЬКО аудиту — вердикт остаётся без объявленного срока.
                "retention_sec": {KIND_AUDIT: 10.0},
            }
        )
        try:
            very_old_ts = time.time() - 10_000_000.0
            sink.append({"kind": KIND_VERDICT, "ts": very_old_ts, "summary": "N-1: брак"})

            sink.purge_expired()

            got = sink.query(kind=KIND_VERDICT)
            assert len(got) == 1, "молчание конфига — не разрешение потерять документ о качестве"
        finally:
            _close(sink)

    def test_kind_with_ttl_is_purged_once_expired(self, tmp_path) -> None:
        """Контрольная проба к предыдущему тесту: срок, который ЗАДАН, обязан работать."""
        db_path = tmp_path / "retention_positive.db"
        sink = make_document_sink({"db_path": str(db_path), "retention_sec": {KIND_AUDIT: 10.0}})
        try:
            very_old_ts = time.time() - 10_000_000.0
            sink.append({"kind": KIND_AUDIT, "ts": very_old_ts, "summary": "protухший"})

            removed = sink.purge_expired()

            assert removed == 1
            assert sink.query(kind=KIND_AUDIT) == []
        finally:
            _close(sink)


class TestFactoryFailureIsNotSilent:
    def test_unusable_db_path_raises_instead_of_returning_none(self, tmp_path) -> None:
        """Отказ фабрики обязан выйти исключением, а не молчаливым ``None``.

        Каталог, под который просится файл БД, сам является ФАЙЛОМ (не директорией) —
        под таким путём ни sqlite, ни ОС не создадут вложенный файл. Это ошибка среды,
        не ошибка пользовательского ввода: значит, отказ обязан быть громким.
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("не директория")
        bad_db_path = blocker / "docs.db"

        with pytest.raises(Exception):
            make_document_sink({"db_path": str(bad_db_path)})
