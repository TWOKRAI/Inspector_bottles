# -*- coding: utf-8 -*-
"""D3 (plans/observability-review-remediation.md): миграция auto_vacuum + честность dropped.

Два независимых свойства:

1. **Миграция унаследованных БД.** Файлы, рождённые ДО фикса Ф5.2/``083b8527``
   (порядок ``journal_mode=WAL`` раньше ``PRAGMA auto_vacuum`` — SQLite молча
   игнорирует пожелание на непустой БД), при открытии сейчас же получают
   ``VACUUM`` — единственный способ реально включить incremental-режим на файле
   с уже существующими таблицами. Гейт — ``PRAGMA user_version``: миграция
   бьёт по файлу РОВНО ОДИН раз, не на каждом открытии (VACUUM переписывает
   файл целиком и блокирует писателей — дорого для горячего пути).

2. **Гипотеза отчёта «rollback» — СНЯТА, не воспроизведена.** ``append_records``
   при ``sqlite3.OperationalError`` действительно не делает explicit
   ``rollback()`` (после отлова коннекция остаётся в открытой, но ПУСТОЙ
   транзакции — Python's sqlite3 issues implicit ``BEGIN`` до первого INSERT,
   и это происходит раньше, чем SQLite пытается взять writer-lock под WAL).
   Прямая репродукция реальной блокировки (вторая коннекция держит
   ``BEGIN IMMEDIATE``, ``busy_timeout`` стора укорочен) двумя размерами
   батча (3 и 20000 строк) показала: ``total_changes`` после отказа = 0 —
   под однописательской моделью WAL SQLite либо получает writer-lock ДО
   первой строки батча, либо не получает его вовсе; частичная запись батча
   при "database is locked" физически недостижима (once-acquired writer-lock
   держится до конца транзакции, никто не может её прервать посередине).
   Значит ``dropped`` считает РОВНО то, что реально потеряно — не больше.
   Правка (rollback) НЕ внесена: гипотеза не воспроизвелась, вносить её
   значило бы чинить то, что не сломано.
"""

from __future__ import annotations

import sqlite3
from typing import Any, List

from multiprocess_framework.modules.channel_routing_module.observability import observability_store as _store_mod
from multiprocess_framework.modules.channel_routing_module.observability.observability_store import (
    ObservabilityStore,
)


def _legacy_shaped_db(path: str, rows: int = 1) -> None:
    """Файл в ТОЧНОСТИ форме, найденной в ``logs/live_2026_07_28/observability.db``:

    полная современная схема (process/severity_number на месте), но
    ``auto_vacuum`` не сработал — порядок PRAGMA как до фикса 083b8527:
    ``journal_mode=WAL`` выставлен РАНЬШЕ ``auto_vacuum``.
    """
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")  # легаси-порядок — баг Ф5.2
    conn.execute("PRAGMA auto_vacuum=INCREMENTAL")  # молча не применится: WAL уже занял слот
    conn.execute(
        """
        CREATE TABLE records (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            kind     TEXT NOT NULL,
            process  TEXT,
            module   TEXT NOT NULL,
            ts       REAL NOT NULL,
            severity TEXT,
            severity_number INTEGER,
            message  TEXT,
            extra    TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO records (kind, process, module, ts, severity, severity_number, message, extra) "
        "VALUES ('log','camera_0','worker_module',?,'info',9,?,'{}')",
        [(float(i), f"легаси-{i}") for i in range(rows)],
    )
    conn.commit()
    conn.close()


class TestAutoVacuumMigration:
    def test_legacy_db_ends_up_incremental_after_open(self, tmp_path: Any) -> None:
        db = str(tmp_path / "legacy.db")
        _legacy_shaped_db(db, rows=3)
        raw = sqlite3.connect(db)
        assert raw.execute("PRAGMA auto_vacuum").fetchone()[0] == 0, "тест не воспроизводит легаси-условие"
        raw.close()

        store = ObservabilityStore(db)
        try:
            assert store._conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
            assert store.count() == 3, "VACUUM обязан быть транзакционным — строки не теряются"
        finally:
            store.close()

    def test_user_version_marks_migration_done(self, tmp_path: Any) -> None:
        db = str(tmp_path / "legacy.db")
        _legacy_shaped_db(db)
        store = ObservabilityStore(db)
        try:
            # Задача 1.6 добавила вторую миграцию под ТОТ ЖЕ гейт, поэтому число
            # выросло. Свойство здесь — «миграция auto_vacuum отмечена как
            # сделанная», то есть версия НЕ НИЖЕ её порога; равенство
            # закрепляло соседнюю миграцию, а не эту.
            version = int(store._conn.execute("PRAGMA user_version").fetchone()[0])
            assert version >= _store_mod._AUTO_VACUUM_SCHEMA_VERSION
        finally:
            store.close()

    def test_migration_runs_exactly_once_across_reopens(self, tmp_path: Any, monkeypatch: Any) -> None:
        """Гейт по user_version — не по «маленький ли файл»: три открытия подряд,
        VACUUM (видимый через emergency_log) обязан отработать только на первом."""
        db = str(tmp_path / "legacy.db")
        _legacy_shaped_db(db)

        calls: List[Any] = []
        monkeypatch.setattr(_store_mod, "emergency_log", lambda *a, **kw: calls.append(a))

        for _ in range(3):
            store = ObservabilityStore(db)
            store.close()

        # Голосов у открытия теперь может быть несколько (1.6 добавила отчёт о
        # построении индекса), поэтому считается ИМЕННО VACUUM, а не «сколько
        # раз что-то сказали»: счёт по всем сообщениям сторожил бы соседа.
        vacuums = [c for c in calls if len(c) > 2 and "auto_vacuum" in str(c[2])]
        assert len(vacuums) == 1, f"VACUUM отработал не ровно один раз: {calls}"

    def test_fresh_db_never_needs_vacuum(self, tmp_path: Any, monkeypatch: Any) -> None:
        """На НОВОМ файле auto_vacuum применяется сразу же (пустая БД, страниц ещё
        нет) — VACUUM для миграции не нужен вовсе, горячий путь открытия им не
        придавлен."""
        calls: List[Any] = []
        monkeypatch.setattr(_store_mod, "emergency_log", lambda *a, **kw: calls.append(a))

        store = ObservabilityStore(str(tmp_path / "new.db"))
        try:
            assert store._conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
            assert calls == [], "VACUUM позвался там, где режим и так применился"
        finally:
            store.close()

    def test_user_version_gate_skips_the_pragma_read_on_repeat_opens(self, tmp_path: Any, monkeypatch: Any) -> None:
        """``mode == 0`` сам по себе НЕ доказывает, что гейт по ``user_version``
        что-то делает: раз ``VACUUM`` уже перевёл файл в режим 2, повторный
        ``PRAGMA auto_vacuum`` тоже читал бы 2 и не звал VACUUM снова — то есть
        одного счётчика ``emergency_log`` мало, чтобы отличить «гейт по версии
        реально останавливает работу ДО чтения PRAGMA» от «гейт по режиму
        останавливает её ПОСЛЕ». Здесь проверяется первое — трассировкой SQL.
        """
        db = str(tmp_path / "legacy.db")
        _legacy_shaped_db(db)
        real_connect = sqlite3.connect
        executed: List[str] = []

        def _traced_connect(*a: Any, **kw: Any) -> sqlite3.Connection:
            conn = real_connect(*a, **kw)
            conn.set_trace_callback(lambda sql: executed.append(sql))
            return conn

        monkeypatch.setattr(_store_mod.sqlite3, "connect", _traced_connect)

        store1 = ObservabilityStore(db)
        store1.close()
        executed.clear()

        store2 = ObservabilityStore(db)
        store2.close()

        # Точное совпадение: SET-форма ("PRAGMA auto_vacuum=INCREMENTAL", в
        # _init_schema безусловно) не в счёт — ищем именно READ-форму, которую
        # исполняет _migrate_auto_vacuum.
        assert "PRAGMA auto_vacuum" not in executed, (
            f"гейт по user_version не остановил повторное чтение PRAGMA: {executed}"
        )

    def test_memory_db_is_not_migrated(self) -> None:
        """``:memory:`` не переживает reopen — миграция для неё бессмысленна и
        не должна падать (VACUUM на ``:memory:`` тоже штатен, но незачем)."""
        store = ObservabilityStore(":memory:")
        try:
            store.append_records([{"kind": "log", "module": "m", "ts": 1.0, "severity": "info", "message": "x"}])
            assert store.count() == 1
        finally:
            store.close()


class TestRollbackHypothesisNotReproduced:
    """Свойство D3: ``dropped`` не завышает потерю при реальной блокировке драйвера.

    Ошибка получена НЕ ``raise``'ом внутри теста, а настоящей ``sqlite3.OperationalError``
    от драйвера — вторая коннекция держит ``BEGIN IMMEDIATE`` (реальный writer-lock под
    WAL), ``busy_timeout`` стора укорочен, чтобы тест не ждал секунды.
    """

    def test_dropped_equals_actual_loss_not_more(self, tmp_path: Any) -> None:
        db = str(tmp_path / "obs.db")
        store = ObservabilityStore(db)
        store._conn.execute("PRAGMA busy_timeout=150")

        blocker = sqlite3.connect(db, timeout=0)
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute(
            "INSERT INTO records (kind, process, module, ts, severity, severity_number, message, extra) "
            "VALUES ('log','x','worker_module',9999,'info',9,'blocker','{}')"
        )

        batch = [
            {"kind": "log", "module": "m", "ts": float(i), "severity": "info", "message": f"row-{i}"} for i in range(3)
        ]
        # ДЕЛЬТА, а не абсолют: соединение уже меняло строки на инициализации
        # (миграции, построение индекса 1.6). Ноль здесь закреплял «ничего не
        # делали ВООБЩЕ», а свойство — «этот батч не записал ничего».
        changes_before = store._conn.total_changes
        n = store.append_records(batch)
        assert n == 0, "под реальной блокировкой append обязан отказать, а не пройти"
        dropped_after_failure = store.dropped
        assert dropped_after_failure == 3
        assert store._conn.total_changes == changes_before, "под WAL частичной записи батча при locked не бывает"

        blocker.rollback()
        blocker.close()

        store.append_records([{"kind": "log", "module": "m", "ts": 1.0, "severity": "info", "message": "final"}])
        try:
            assert store.dropped == 3, "dropped не должен расти на успешном append"
            assert store.count() == 1, (
                f"count={store.count()}, dropped={store.dropped} — если бы часть неудачного "
                "батча тихо утекла в файл, count был бы больше 1"
            )
        finally:
            store.close()

    def test_dropped_equals_actual_loss_large_batch(self, tmp_path: Any) -> None:
        """Тот же снаряд, но батч на четыре порядка больше — если бы частичная
        запись где-то была возможна (не на первой строке), большой батч её бы
        обнажил."""
        db = str(tmp_path / "obs.db")
        store = ObservabilityStore(db)
        store._conn.execute("PRAGMA busy_timeout=150")

        blocker = sqlite3.connect(db, timeout=0)
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute(
            "INSERT INTO records (kind, process, module, ts, severity, severity_number, message, extra) "
            "VALUES ('log','x','worker_module',9999,'info',9,'blocker','{}')"
        )

        big_batch = [
            {"kind": "log", "module": "m", "ts": float(i), "severity": "info", "message": f"row-{i}"}
            for i in range(2000)
        ]
        changes_before = store._conn.total_changes
        n = store.append_records(big_batch)
        assert n == 0
        assert store.dropped == 2000
        assert store._conn.total_changes == changes_before

        blocker.rollback()
        blocker.close()
        try:
            assert store.count() == 0, "ни одна строка большого отклонённого батча не просочилась"
        finally:
            store.close()
