# -*- coding: utf-8 -*-
"""Задача 3.1 (`plans/observability-roadmap.md`, этап 3): второй стор не пухнет.

Свойство, которое здесь сторожится, — не «PRAGMA выставлена», а **файл уменьшается после
ретеншена**. Разница несущая: `auto_vacuum` без `incremental_vacuum` не уменьшает файл
никогда, а `incremental_vacuum` без `auto_vacuum` — не-операция. Поэтому у каждого
утверждения есть КОНТРОЛЬ: тот же сценарий на файле, оставленном в режиме 0.

Файловая БД, не in-memory: адаптер берёт новое соединение на каждый вызов, и `:memory:`
между ними не переживает. Все проверки режима — ПОСТОРОННИМ соединением к файлу, потому
что предмет спора именно в том, что записано в файл, а не в том, что мы просили.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, List

import pytest

from Services.documents import KIND_AUDIT, wiring
from Services.documents.store import DocumentStore
from Services.documents.wiring import make_document_sink
from Services.sql.adapters.sqlite import SQLiteSyncAdapter
from Services.sql.core.adapter_factory import create_sync_adapter

#: Один документ ~16 КиБ (четыре страницы по 4096) — чтобы удаление создавало СОТНИ
#: свободных страниц. На десятке строк форма вызова, отдающая одну страницу за раз,
#: прошла бы. Крупные документы вместо многих: цена теста — в числе вставок, каждая
#: из которых берёт своё соединение (NullPool).
_BIG_SUMMARY = "б" * 16000
_ROWS = 150


# ---------------------------------------------------------------------------
# инструменты
# ---------------------------------------------------------------------------


def _file_state(path: str) -> Dict[str, Any]:
    """Что записано в ФАЙЛЕ — сторонним соединением, без наших абстракций."""
    conn = sqlite3.connect(path)
    try:
        return {
            "auto_vacuum": int(conn.execute("PRAGMA auto_vacuum").fetchone()[0]),
            "journal_mode": str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower(),
            "user_version": int(conn.execute("PRAGMA user_version").fetchone()[0]),
            "freelist": int(conn.execute("PRAGMA freelist_count").fetchone()[0]),
            "rows": int(conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]),
            "size": os.path.getsize(path),
        }
    finally:
        conn.close()


def _close(sink) -> None:
    close = getattr(sink, "close", None)
    if callable(close):
        close()


def _fill(sink, rows: int = _ROWS, age_sec: float = 10_000_000.0) -> None:
    old_ts = time.time() - age_sec
    for i in range(rows):
        assert sink.append({"kind": KIND_AUDIT, "ts": old_ts + i, "summary": _BIG_SUMMARY})


def _born_before_the_task(tmp_path, name: str, rows: int = _ROWS) -> str:
    """Файл, рождённый ДОРЕФОРМЕННЫМ путём — продовым кодом, а не руками.

    Гейт миграции опущен до 0 (``user_version 0 >= 0`` → выход раньше PRAGMA), поэтому
    файл получается ровно таким, каким его рождала фабрика до задачи 3.1: WAL есть,
    ``auto_vacuum`` = 0. Собирать такой файл руками нельзя — тогда тест доказывал бы,
    что мигрирует НАША заготовка, а не то, что лежит у владельца на диске (шрам M-5
    задачи 1.6: «свежий файл со сброшенным user_version» легаси-условие не воспроизводил).
    """
    db_path = str(tmp_path / name)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(wiring, "SCHEMA_VERSION", 0)
        sink = make_document_sink({"db_path": db_path})
        try:
            _fill(sink, rows)
        finally:
            _close(sink)

    state = _file_state(db_path)
    assert state["auto_vacuum"] == 0, "тест не воспроизводит легаси-условие: режим уже рабочий"
    assert state["rows"] == rows
    return db_path


class _FakeAdapter:
    """Двойник адаптера БЕЗ способности возвращать страницы (PostgreSQL/старый sqlite)."""

    def __init__(self, *, rowcount: int = 1) -> None:
        self.executed: List[str] = []
        self._rowcount = rowcount

    def execute(self, sql: str, params: Dict[str, Any] | None = None) -> int:
        self.executed.append(sql)
        return self._rowcount


class _FakeVacuumAdapter(_FakeAdapter):
    """Двойник со способностью — и умеющий ОТКАЗАТЬ.

    Дубль, который всегда успешен, глушит гейт: тест «отказ не роняет ретеншен» на таком
    двойнике был бы зелёным при любой реализации, включая отсутствующую.
    """

    def __init__(self, *, rowcount: int = 1, raises: bool = False) -> None:
        super().__init__(rowcount=rowcount)
        self.calls = 0
        self._raises = raises

    def incremental_vacuum(self) -> int:
        self.calls += 1
        if self._raises:
            raise sqlite3.OperationalError("database is locked")
        return 7


class _HostileConn:
    """Прокси соединения: подменяет МИР вокруг миграции, а не её логику.

    Всё, кроме ``VACUUM``, идёт в настоящую БД. ``VACUUM`` ведёт себя одним из двух
    способов, которые в природе есть, а в тесте иначе не воспроизводятся:

    * ``raise`` — диск полон под копию (``VACUUM`` требует места ≈ размера БД);
    * ``ignore`` — молча не сделал ничего. Ровно это делает SQLite с
      ``PRAGMA auto_vacuum`` на непустом файле, и ровно из-за этого миграция вообще
      существует.
    """

    def __init__(self, sa_conn: Any, *, vacuum: str) -> None:
        self._raw = sa_conn.execution_options(isolation_level="AUTOCOMMIT").connection.driver_connection
        self._vacuum = vacuum

    def execution_options(self, **_kw: Any) -> "_HostileConn":
        return self

    @property
    def connection(self) -> "_HostileConn":
        return self

    @property
    def driver_connection(self) -> "_HostileConn":
        return self

    def execute(self, sql: str) -> Any:
        # startswith, а не подстрока: `PRAGMA auto_vacuum` тоже содержит слово VACUUM,
        # и грубая проверка глушила бы ЧТЕНИЕ режима — то есть двойник ломал бы не то,
        # что собирался. Поймано первым же прогоном.
        if sql.strip().upper().startswith("VACUUM"):
            if self._vacuum == "raise":
                raise sqlite3.OperationalError("database or disk is full")
            return None
        return self._raw.execute(sql)


class _HostileAdapter(SQLiteSyncAdapter):
    """Настоящий адаптер в враждебной среде: миграция НЕ подменена, она унаследована."""

    vacuum_behaviour = "raise"

    @contextmanager
    def connection(self):  # type: ignore[override]
        with super().connection() as conn:
            yield _HostileConn(conn, vacuum=self.vacuum_behaviour)


# ---------------------------------------------------------------------------
# миграция унаследованного файла
# ---------------------------------------------------------------------------


class TestLegacyFileIsMigrated:
    def test_mode_goes_from_0_to_2_and_documents_survive(self, tmp_path) -> None:
        """Приёмка 3.1 дословно: PRAGMA 0 → 2, строки целы."""
        db_path = _born_before_the_task(tmp_path, "legacy.db")

        sink = make_document_sink({"db_path": db_path})
        try:
            assert sink.auto_vacuum == 2, "фабрика обязана сообщать ФАКТ, а не пожелание"
        finally:
            _close(sink)

        state = _file_state(db_path)
        assert state["auto_vacuum"] == 2
        assert state["rows"] == _ROWS, "VACUUM не имеет права потерять ни один документ"
        assert state["user_version"] == wiring.SCHEMA_VERSION
        assert state["journal_mode"] == "wal", "миграция не имеет права снять WAL"

    def test_stamped_file_is_not_vacuumed_again(self, tmp_path) -> None:
        """Гейт ``user_version`` читается, а не декорация.

        Файл с режимом 0, но уже помеченный версией, обязан остаться в режиме 0: иначе
        ``VACUUM`` (перезапись БД целиком с блокировкой писателей) шёл бы на КАЖДОМ
        открытии плоскости — то есть у каждого из восьми процессов на каждом старте.
        """
        db_path = _born_before_the_task(tmp_path, "stamped.db", rows=5)
        conn = sqlite3.connect(db_path)
        conn.execute(f"PRAGMA user_version = {wiring.SCHEMA_VERSION}")
        conn.commit()
        conn.close()

        sink = make_document_sink({"db_path": db_path})
        try:
            assert sink.auto_vacuum == 0
        finally:
            _close(sink)
        assert _file_state(db_path)["auto_vacuum"] == 0

    def test_fresh_file_is_born_with_the_working_mode(self, tmp_path) -> None:
        """Новый файл обязан родиться правильным, а не починиться следующим открытием."""
        db_path = str(tmp_path / "fresh.db")
        sink = make_document_sink({"db_path": db_path})
        try:
            _fill(sink, rows=3)
            assert sink.auto_vacuum == 2
        finally:
            _close(sink)

        state = _file_state(db_path)
        assert state["auto_vacuum"] == 2
        assert state["journal_mode"] == "wal"
        assert state["user_version"] == wiring.SCHEMA_VERSION


class TestRefusalIsNamedAndNotStamped:
    def test_locked_file_refuses_and_keeps_the_version_unstamped(self, tmp_path) -> None:
        """Восемь процессов открывают файл почти одновременно — второй получит замок.

        Блокировка здесь НАСТОЯЩАЯ (сторонняя транзакция ``BEGIN EXCLUSIVE``), а не
        подделанная исключением: воспроизводится ровно то, что случится на стенде.
        Требование двойное — отказ назван И версия не проштампована, иначе следующий
        старт счёл бы миграцию выполненной и файл остался бы в режиме 0 навсегда.
        """
        db_path = _born_before_the_task(tmp_path, "locked.db", rows=5)

        blocker = sqlite3.connect(db_path, isolation_level=None, timeout=0.1)
        blocker.execute("BEGIN EXCLUSIVE")
        blocker.execute("CREATE TABLE IF NOT EXISTS _lock_probe(x)")
        try:
            adapter = create_sync_adapter(
                {
                    "url": f"sqlite:///{db_path}",
                    "dialect": "sqlite",
                    "fork_safe": True,
                    "connect_args": {"timeout": 0.1, "check_same_thread": False},
                },
                dialect="sqlite",
            )
            adapter.setup()
            try:
                outcome = adapter.migrate_to_incremental_auto_vacuum(wiring.SCHEMA_VERSION)
            finally:
                adapter.dispose()
        finally:
            blocker.rollback()
            blocker.close()

        assert outcome["error"], "отказ обязан быть НАЗВАН, а не проглочен"
        assert outcome["mode"] == 0
        assert outcome["migrated"] is False
        assert _file_state(db_path)["user_version"] == 0, "неудавшаяся миграция не имеет права пометиться выполненной"

    def _hostile_outcome(self, db_path: str, behaviour: str) -> Dict[str, Any]:
        adapter = _HostileAdapter(
            {
                "url": f"sqlite:///{db_path}",
                "dialect": "sqlite",
                "fork_safe": True,
                "connect_args": {"timeout": 1.0, "check_same_thread": False},
            }
        )
        adapter.vacuum_behaviour = behaviour
        adapter.setup()
        try:
            return adapter.migrate_to_incremental_auto_vacuum(wiring.SCHEMA_VERSION)
        finally:
            adapter.dispose()

    def test_vacuum_that_raises_is_named_and_not_stamped(self, tmp_path) -> None:
        """Диск полон под копию: отказ назван, версия чиста, плоскость жива."""
        db_path = _born_before_the_task(tmp_path, "diskfull.db", rows=5)

        outcome = self._hostile_outcome(db_path, "raise")

        assert "full" in outcome["error"], f"отказ обязан назвать причину, получено {outcome['error']!r}"
        assert outcome["migrated"] is False
        assert _file_state(db_path)["user_version"] == 0

    def test_silently_ignored_pragma_is_not_stamped_as_done(self, tmp_path) -> None:
        """ГЛАВНАЯ гарантия штампа, и блокировкой файла её не проверить.

        Блокировка запрещает и запись версии тоже — там «версия чиста» держится на
        невозможности записи, а не на проверке режима. Здесь ``VACUUM`` молча не делает
        ничего (ровно как SQLite с PRAGMA на непустом файле), записи при этом проходят,
        отказа нет — и версия обязана остаться нулевой, потому что РЕЖИМ не стал целевым.
        Проштампуй её здесь — и файл остался бы в режиме 0 навсегда: следующий старт
        счёл бы миграцию выполненной.
        """
        db_path = _born_before_the_task(tmp_path, "silent.db", rows=5)

        outcome = self._hostile_outcome(db_path, "ignore")

        assert outcome["error"] == "", "отказа не было — придумывать его нельзя"
        assert outcome["mode"] == 0
        assert outcome["migrated"] is False
        assert _file_state(db_path)["user_version"] == 0, (
            "режим не стал рабочим, а миграция помечена выполненной — файл больше никогда не починится"
        )


class TestOutcomeIsSpoken:
    def test_migration_price_is_named(self, tmp_path, caplog) -> None:
        db_path = _born_before_the_task(tmp_path, "voice.db", rows=5)
        with caplog.at_level(logging.WARNING, logger="Services.documents.wiring"):
            sink = make_document_sink({"db_path": db_path})
            _close(sink)
        assert any("миграция auto_vacuum" in r.getMessage() for r in caplog.records)

    def test_silent_zero_is_named(self, caplog) -> None:
        """Режим остался нулевым БЕЗ отказа — самый тихий исход из трёх.

        Двойник возвращает ровно эту форму (``mode=0``, ``error=''``): она означает, что
        SQLite молча проигнорировал PRAGMA. Не назови её — и единственным следом остался бы
        растущий файл через месяц.
        """

        class _SilentAdapter:
            def migrate_to_incremental_auto_vacuum(self, schema_version: int) -> Dict[str, Any]:
                return {"mode": 0, "migrated": False, "duration_sec": 0.0, "error": ""}

        with caplog.at_level(logging.WARNING, logger="Services.documents.wiring"):
            mode = wiring._migrate_auto_vacuum(_SilentAdapter(), "some/docs.db")

        assert mode == 0
        assert any("молча" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# ретеншен возвращает байты
# ---------------------------------------------------------------------------


class TestRetentionReturnsBytes:
    def test_purge_shrinks_the_file(self, tmp_path) -> None:
        """Приёмка 3.1: purge режет БАЙТЫ, с числами до/после."""
        db_path = str(tmp_path / "shrink.db")
        sink = make_document_sink({"db_path": db_path, "retention_sec": {KIND_AUDIT: 10.0}})
        try:
            _fill(sink)
            before = _file_state(db_path)

            removed = sink.purge_expired()
            after = _file_state(db_path)

            assert removed == _ROWS
            assert after["size"] < before["size"] / 2, (
                f"файл не уменьшился: {before['size']} -> {after['size']} байт "
                f"(страниц возвращено {sink.pages_reclaimed})"
            )
            assert sink.pages_reclaimed > 0
            assert sink.reclaim_failed == 0
        finally:
            _close(sink)

    def test_control_file_left_at_mode_0_does_not_shrink(self, tmp_path, monkeypatch) -> None:
        """КОНТРОЛЬ к предыдущему тесту: тот же ретеншен без режима — файл стоит на месте.

        Без этой пары предыдущий тест доказывал бы только «DELETE что-то делает». Замер:
        при ``auto_vacuum=0`` удаление 95 % строк даёт 8.70 → 8.70 МиБ.
        """
        db_path = _born_before_the_task(tmp_path, "control.db")
        monkeypatch.setattr(wiring, "SCHEMA_VERSION", 0)
        sink = make_document_sink({"db_path": db_path, "retention_sec": {KIND_AUDIT: 10.0}})
        try:
            assert sink.auto_vacuum == 0, "контроль требует режима 0, иначе он не контроль"
            before = _file_state(db_path)

            removed = sink.purge_expired()
            after = _file_state(db_path)

            assert removed == _ROWS, "строки обязаны удалиться и без режима — DELETE работает всегда"
            assert after["size"] == before["size"], "в режиме 0 файл уменьшиться не может"
            assert after["freelist"] > 0, "страницы обязаны остаться во freelist"
        finally:
            _close(sink)

    def test_every_free_page_is_returned_not_one_per_call(self, tmp_path) -> None:
        """Сторож ФОРМЫ вызова прагмы.

        ``PRAGMA incremental_vacuum`` исполняется шагами. Все штатные формы адаптера
        (``execute``, в том числе с аргументом ``(1000000)``) отдают РОВНО ОДНУ страницу
        из 2116 — замер 2026-08-11. Поэтому проверяется не «файл стал меньше», а
        «свободных страниц не осталось»: заменит кто-нибудь дорогу на штатную — файл
        всё равно чуть уменьшится, и проверка размера это пропустит.
        """
        db_path = str(tmp_path / "drain.db")
        sink = make_document_sink({"db_path": db_path, "retention_sec": {KIND_AUDIT: 10.0}})
        try:
            _fill(sink)
            sink.purge_expired()

            assert _file_state(db_path)["freelist"] == 0
            assert sink.pages_reclaimed > 100, (
                f"возвращено страниц: {sink.pages_reclaimed} — похоже на форму «одна за вызов»"
            )
        finally:
            _close(sink)

    def test_purge_that_removed_nothing_does_not_pay_for_reclaim(self) -> None:
        """Цена уборки не платится на каждом такте heartbeat впустую."""
        # Ретеншен есть, но удалять нечего: двойник отвечает «строк не тронуто».
        adapter = _FakeVacuumAdapter(rowcount=0)
        store = DocumentStore(adapter, retention_sec={KIND_AUDIT: 10.0}, dialect="sqlite")

        assert store.purge_expired() == 0
        assert adapter.calls == 0, "нет удалений — нет свободных страниц — незачем звать уборку"

    def test_reclaim_failure_does_not_break_retention(self) -> None:
        """Документы уже удалены; отказ уборки не имеет права уронить такт — но обязан считаться."""
        adapter = _FakeVacuumAdapter(raises=True)
        store = DocumentStore(adapter, retention_sec={KIND_AUDIT: 10.0}, dialect="sqlite")

        removed = store.purge_expired()

        assert removed == 1, "удаление состоялось — ретеншен обязан отчитаться о нём"
        assert store.reclaim_failed == 1
        assert store.pages_reclaimed == 0


class TestOtherEnginesAreNotTouched:
    def test_non_sqlite_dialect_is_left_alone(self) -> None:
        """PostgreSQL/MySQL ведут своё хозяйство сами — звать их прагмами нечем."""
        adapter = _FakeVacuumAdapter()
        store = DocumentStore(adapter, retention_sec={KIND_AUDIT: 10.0}, dialect="postgresql")

        assert store.purge_expired() == 1
        assert adapter.calls == 0

    def test_adapter_without_the_capability_is_not_a_failure(self) -> None:
        """Отсутствие способности у адаптера — не отказ (та же проверка, что у close/dispose)."""
        adapter = _FakeAdapter()
        store = DocumentStore(adapter, retention_sec={KIND_AUDIT: 10.0}, dialect="sqlite")

        assert store.purge_expired() == 1
        assert store.reclaim_failed == 0
