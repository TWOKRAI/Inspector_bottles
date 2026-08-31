# -*- coding: utf-8 -*-
"""
SQLiteSyncAdapter / SQLiteAsyncAdapter — адаптеры для SQLite.

Используется для тестов (in-memory) и лёгких сценариев.

Здесь же живёт обслуживание ФАЙЛА БД (`auto_vacuum`, возврат свободных страниц):
знание о том, что база — это файл со своим режимом страниц, есть только у sqlite,
и вызывающему (плоскость документов) незачем видеть ни SQLAlchemy, ни DBAPI.
"""

import time
from typing import Any, Dict, Union

from Services.sql.adapters.sync_adapter import BaseSyncAdapter
from Services.sql.adapters.async_adapter import BaseAsyncAdapter
from Services.sql.configs import SQLManagerConfig

#: Значение `PRAGMA auto_vacuum` для режима INCREMENTAL. Не FULL: полный режим
#: перекладывает страницы на КАЖДОМ commit, то есть платит писатель на горячем пути.
_AUTO_VACUUM_INCREMENTAL = 2


class SQLiteSyncAdapter(BaseSyncAdapter):
    """Синхронный адаптер для SQLite."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)

    def migrate_to_incremental_auto_vacuum(self, schema_version: int) -> Dict[str, Any]:
        """Разово перевести файл БД на реально работающий ``auto_vacuum=INCREMENTAL``.

        **Зачем.** Без этого режима удаление строк не уменьшает файл никогда: страницы
        уходят во freelist и переиспользуются, а ``PRAGMA incremental_vacuum`` становится
        не-операцией. Замер (2026-08-11, файл 8.70 МиБ, 20 000 строк, удалено 95 %):
        при ``auto_vacuum=0`` DELETE + ``incremental_vacuum`` дают 8.70 → **8.70 МиБ**,
        при режиме 2 — 8.71 → **0.44 МиБ**.

        **Почему миграция, а не одна PRAGMA при создании.** ``PRAGMA auto_vacuum=...``
        применяется только к БД, в которой ещё нет таблиц; на непустом файле SQLite
        не отказывает, а **молча игнорирует** пожелание, и реально меняет режим страниц
        только ``VACUUM``. Файлы, рождённые до этой задачи, уже содержат данные.

        **Гейт — ``PRAGMA user_version``**, а не размер файла: ``VACUUM`` перезаписывает
        БД целиком и держит писателей, гонять его на каждом открытии недопустимо. Версия
        штампуется ТОЛЬКО когда режим действительно стал целевым — иначе молча
        проигнорированная PRAGMA была бы записана как выполненная миграция, и следующий
        старт не попробовал бы снова.

        ``VACUUM`` транзакционен и требует свободного места ≈ размера БД: при сбое посреди
        него файл остаётся прежним, отдельная защита копированием не нужна.

        Args:
            schema_version: значение, которым помечается уже мигрированный файл.
                Политика вызывающего: номер живёт в его схеме, не в адаптере.

        Returns:
            ``mode`` — режим, который файл имеет ФАКТИЧЕСКИ после вызова (не тот, который
            просили); ``migrated`` — был ли выполнен ``VACUUM``; ``duration_sec`` — его цена;
            ``error`` — имя отказа или пустая строка.

            Отказ возвращается, а не выбрасывается, намеренно: не сумев **оптимизировать**
            файл, плоскость продолжает работать на режиме 0 — это дороже по байтам, но
            рабочее. Восемь процессов стенда открывают файл почти одновременно, и второй
            получит на ``VACUUM`` заблокированную БД; ронять из-за этого плоскость нельзя.
            Молчать о таком тоже нельзя — поэтому отказ назван в ``error``, и вызывающий
            обязан его озвучить.
        """
        if not self._engine:
            raise RuntimeError("Adapter not initialized. Call setup() first.")

        outcome: Dict[str, Any] = {"mode": 0, "migrated": False, "duration_sec": 0.0, "error": ""}
        try:
            with self.connection() as conn:
                # AUTOCOMMIT несущий, а не косметика: `VACUUM` внутри транзакции
                # запрещён самим SQLite, а SQLAlchemy открывает её на первом execute.
                raw = conn.execution_options(isolation_level="AUTOCOMMIT").connection.driver_connection
                outcome["mode"] = int(raw.execute("PRAGMA auto_vacuum").fetchone()[0])
                if int(raw.execute("PRAGMA user_version").fetchone()[0]) >= int(schema_version):
                    return outcome
                if outcome["mode"] != _AUTO_VACUUM_INCREMENTAL:
                    started = time.monotonic()
                    raw.execute("PRAGMA auto_vacuum=INCREMENTAL")
                    raw.execute("VACUUM")
                    outcome["duration_sec"] = time.monotonic() - started
                    outcome["mode"] = int(raw.execute("PRAGMA auto_vacuum").fetchone()[0])
                    outcome["migrated"] = outcome["mode"] == _AUTO_VACUUM_INCREMENTAL
                if outcome["mode"] == _AUTO_VACUUM_INCREMENTAL:
                    # PRAGMA не принимает `?`-плейсхолдеры; значение приведено к int выше.
                    raw.execute(f"PRAGMA user_version = {int(schema_version)}")  # nosec B608
        except Exception as e:  # noqa: BLE001 — см. Returns: отказ оптимизации не роняет плоскость
            outcome["error"] = f"{type(e).__name__}: {e}"
        return outcome

    def incremental_vacuum(self) -> int:
        """Вернуть ОС свободные страницы файла. Возвращает, сколько страниц отдано.

        Требует режима, который ставит :meth:`migrate_to_incremental_auto_vacuum`. При
        ``auto_vacuum=0`` вызов законен и делает ровно ничего — вернёт 0.

        **ФОРМА ВЫЗОВА ЗДЕСЬ НЕСУЩАЯ, и штатные ``execute``/``query`` для неё не годятся.**
        Прагма исполняется шагами, и её нужно ДОГНАТЬ до конца — то есть вычерпать курсор.
        Замер всех форм на одинаковом мусоре (2026-08-11, 2116 свободных страниц,
        9 138 176 байт):

        =========================================================  ===================
        форма                                                      результат
        =========================================================  ===================
        ``adapter.execute("PRAGMA incremental_vacuum")``            2116 → 2115, одна страница
        ``adapter.execute("PRAGMA incremental_vacuum(1000000)")``   2116 → 2115, одна страница
        ``adapter.query(...)``                                      ``ResourceClosedError``
        ``conn.exec_driver_sql(...).fetchall()``                    ``ResourceClosedError``
        сырой курсор DBAPI + ``fetchall()``                         2116 → **0**, 0.44 МиБ
        =========================================================  ===================

        Аргумент «сколько страниц» **не заменяет** вычерпывание: с ``(1000000)`` уходит
        та же одна страница. SQLAlchemy для этой прагмы считает, что строк нет, и закрывает
        результат — поэтому единственная работающая дорога идёт через курсор драйвера.
        """
        if not self._engine:
            raise RuntimeError("Adapter not initialized. Call setup() first.")
        with self.connection() as conn:
            raw = conn.execution_options(isolation_level="AUTOCOMMIT").connection.driver_connection
            before = int(raw.execute("PRAGMA freelist_count").fetchone()[0])
            raw.execute("PRAGMA incremental_vacuum").fetchall()
            after = int(raw.execute("PRAGMA freelist_count").fetchone()[0])
        return before - after


class SQLiteAsyncAdapter(BaseAsyncAdapter):
    """Асинхронный адаптер для SQLite (aiosqlite)."""

    def __init__(self, config: Union[SQLManagerConfig, Dict[str, Any]]):
        super().__init__(config)
