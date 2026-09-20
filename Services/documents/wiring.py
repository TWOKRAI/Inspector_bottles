# -*- coding: utf-8 -*-
"""Фабрика стока документов — точка, которую композиционный корень называет СТРОКОЙ.

Фреймворк не имеет права импортировать ``Services`` (правило слоёв 9), а живой сток ему
нужен: аудит смен наблюдаемости рождается внутри процесса фреймворка. Развилку закрыл
вердикт ревью Ф8 (вариант B): фреймворк читает из конфига **import-path фабрики**,
резолвит его importlib'ом и зовёт с dict'ом. Канон не новый — так же грузятся класс
процесса (``class_loader``), оркестратор (``orchestrator_class_path``) и приёмники
логгера (``register_sink_factory``). Статического импорта ``Services`` во фреймворке не
появляется, и знание о том, ЧЕМ реализована плоскость, остаётся у корня.

Отвергнутые альтернативы (полностью — в ``plans/observability-unified-routing.md``,
врезка Task 8.5): generic пер-процессный хук старта (слой ради одного клиента),
``ServiceRegistry`` (хранит классы, а не экземпляры — живой сток из него не достать),
переезд плоскости во фреймворк (втащил бы SQL-стек против правила слоёв).
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from multiprocess_framework.modules._fallback import FallbackLogger
from Services.sql.core.adapter_factory import create_sync_adapter

from .store import DocumentStore

__all__ = ["make_document_sink", "DEFAULT_DB_PATH", "DEFAULT_BUSY_TIMEOUT_SEC"]

# Task 4.11: адресат этих строк — оператор/интегратор, читающий журнал (цена
# миграции, отказ, тихий ноль), а не самоотчёт сломавшегося маршрута
# наблюдаемости — поэтому вид (`FallbackLogger`), а не аварийный выход
# (`emergency_log`). Имя стока — `__name__`, как у остальных видов дерева.
_logger = FallbackLogger(__name__)

#: Файл БД по умолчанию. Не в каталоге логов намеренно: у логов свой ретеншен
#: (7 дней / 200 МБ, Ф6.9), и документ, положенный рядом, однажды уедет вместе с ними.
DEFAULT_DB_PATH = "data/documents.db"

#: Сколько ждать освобождения файла, прежде чем считать запись отказавшей.
#: Замер конкуренции (6 процессов × 50 записей): медиана 3.6 мс, max 928 мс —
#: то есть 5 с покрывают наблюдённый хвост с запасом, а не «на глаз».
DEFAULT_BUSY_TIMEOUT_SEC = 5.0

#: Версия схемы файла `documents.db` — гейт разовой миграции `auto_vacuum` (задача 3.1).
#: Отдельная от `user_version` стора наблюдаемости: файлы разные, счётчик у каждого свой.
SCHEMA_VERSION = 1


def make_document_sink(config: Optional[Dict[str, Any]] = None) -> DocumentStore:
    """Собрать сток документов по dict'у конфига (``observability.documents.config``).

    Args:
        config: ``db_path`` — файл БД (дефолт :data:`DEFAULT_DB_PATH`);
            ``retention_sec`` — ``{род: секунды}``, род без срока не удаляется никогда;
            ``busy_timeout_sec`` — ожидание блокировки (дефолт
            :data:`DEFAULT_BUSY_TIMEOUT_SEC`);
            ``dialect``/``url`` — для не-SQLite движка (тогда WAL не трогается).
            ``purge_interval_sec`` читает вызывающий (такт уборки — его дело), здесь
            игнорируется.

    Returns:
        :class:`DocumentStore`. Атрибуты ``journal_mode`` и ``auto_vacuum`` — режимы,
        которые БД **фактически** приняла (не те, которые мы попросили). Оба читаются
        обратно с файла именно поэтому: PRAGMA умеет молча ничего не сделать.

    Raises:
        Наружу выходит всё, чем откажет открытие БД: каталог не создать, файл занят,
        диалект неизвестен. Глушить нельзя — молчаливый ``None`` здесь неотличим от
        «плоскость не настроена», а это ровно тот класс «проглоченный сбой», которым
        занимается фаза. Громкость обеспечивает вызывающий (WARNING с адресом ключа).

    **Почему WAL и busy_timeout ставятся ЗДЕСЬ, а не остаются дефолтом драйвера**
    (Р-8.5-Б). Замер «300/300, dropped=0» держался на дефолте ``sqlite3`` (``timeout=5``),
    то есть свойство было случайным: смена драйвера или адаптера сняла бы его молча.
    ``ObservabilityStore`` фреймворка WAL включает явно — два стора одного репозитория
    не должны расходиться в дисциплине конкурентной записи.

    **Почему у двух настроек разные механизмы.** ``journal_mode=WAL`` липнет к ФАЙЛУ БД,
    поэтому достаточно одного PRAGMA при создании. ``busy_timeout`` живёт в СОЕДИНЕНИИ,
    а адаптер берёт новое соединение на каждый вызов (NullPool) — PRAGMA не пережил бы
    и одного вызова, и его место в ``connect_args``, куда он доезжает до
    ``sqlite3.connect`` на каждом открытии.
    """
    cfg = dict(config or {})
    dialect = str(cfg.get("dialect") or "sqlite")
    db_path = str(cfg.get("db_path") or DEFAULT_DB_PATH)
    busy_timeout = float(cfg.get("busy_timeout_sec") or DEFAULT_BUSY_TIMEOUT_SEC)

    if dialect == "sqlite":
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        url = str(cfg.get("url") or f"sqlite:///{db_path}")
        connect_args = {
            # Ожидание освобождения файла вместо немедленного "database is locked".
            "timeout": busy_timeout,
            # Писателей у стока два (аудит из потока команд, вердикты с линии).
            # При NullPool соединение не переживает вызова и потоков не пересекает,
            # то есть сегодня проверка не мешает; снимаем её на случай смены пула
            # (StaticPool для in-memory уже шарит соединение между потоками).
            "check_same_thread": False,
        }
    else:
        url = str(cfg.get("url") or "")
        connect_args = {}
        if not url:
            raise ValueError(f"documents: dialect={dialect!r} требует явного 'url' в конфиге")

    adapter = create_sync_adapter(
        {
            "url": url,
            "dialect": dialect,
            # Процессов-писателей несколько, и каждый форкается от родителя: пул
            # соединений через fork не переживает (см. engine_factory).
            "fork_safe": True,
            "connect_args": connect_args,
        },
        dialect=dialect,
    )
    adapter.setup()

    journal_mode = ""
    auto_vacuum = 0
    if dialect == "sqlite":
        # `auto_vacuum` идёт ДО `journal_mode=WAL`, и порядок здесь **НЕ несущий** —
        # измерено инъекцией: перенос миграции за прагму WAL не покраснил ни одного
        # теста. Причина в том, что режим ставит не PRAGMA, а `VACUUM`, а он работает
        # и на непустом файле. Порядок сохранён как страховка на случай, если однажды
        # `VACUUM` из миграции уберут «как лишний на свежем файле»: тогда шрам
        # D3/ADR-CRM-014 (WAL первым → режим молча остался нулевым) вернётся.
        auto_vacuum = _migrate_auto_vacuum(adapter, db_path)
        # query, а не execute: PRAGMA возвращает строку с принятым режимом, и нам
        # нужен ФАКТ, а не наше пожелание. Отказ принять WAL (сетевая ФС) плоскость
        # не отменяет — она продолжит работать на journal=delete, просто читатель
        # будет блокироваться писателем; режим виден в ``journal_mode``.
        rows = adapter.query("PRAGMA journal_mode=WAL")
        journal_mode = str(rows[0].get("journal_mode", "")) if rows else ""
        # ``synchronous=NORMAL`` здесь НЕ ставится, хотя ObservabilityStore его ставит.
        # Он живёт в СОЕДИНЕНИИ, а адаптер берёт новое на каждый вызов: PRAGMA
        # подействовал бы ровно на то соединение, в котором выполнен, и остался бы
        # названным механизмом без обязательства — то есть строкой, которой верят.
        # Цена честного отказа мала: fsync на commit платится за документ, а
        # документы редки (аудит — единицы на инцидент).

    retention = {str(k): float(v) for k, v in (cfg.get("retention_sec") or {}).items() if v is not None}
    store = DocumentStore(adapter, retention_sec=retention, dialect=dialect)
    store.journal_mode = journal_mode  # type: ignore[attr-defined]
    store.auto_vacuum = auto_vacuum  # type: ignore[attr-defined]
    return store


def _migrate_auto_vacuum(adapter: Any, db_path: str) -> int:
    """Разово перевести файл БД на работающий ``auto_vacuum`` и ОЗВУЧИТЬ исход.

    Механику и замеры держит адаптер
    (:meth:`Services.sql.adapters.sqlite.SQLiteSyncAdapter.migrate_to_incremental_auto_vacuum`);
    здесь — политика: номер версии схемы плоскости и громкость.

    Озвучиваются ТРИ разных исхода, а не один: миграция прошла (названа её цена —
    ``VACUUM`` держит писателей), миграция отказала (файл занят соседним процессом —
    плоскость продолжает на режиме 0 и попробует на следующем старте), режим остался
    нулевым БЕЗ отказа (PRAGMA молча проигнорирована — самый тихий из трёх, и потому
    единственный, который иначе никто бы не заметил).

    Returns:
        Режим, который файл имеет фактически. Ноль — рабочее состояние, просто
        удаление документов не будет уменьшать файл.
    """
    migrate = getattr(adapter, "migrate_to_incremental_auto_vacuum", None)
    if not callable(migrate):
        # Диалект sqlite, но адаптер обслуживания файла не умеет — не наше дело падать.
        return 0

    outcome = migrate(SCHEMA_VERSION)
    mode = int(outcome.get("mode", 0))
    if outcome.get("error"):
        _logger.warning(
            "documents: миграция auto_vacuum на %s не выполнена (%s); плоскость работает "
            "на auto_vacuum=%s — удаление документов не уменьшит файл, попробуем на следующем старте",
            db_path,
            outcome["error"],
            mode,
        )
    elif outcome.get("migrated"):
        _logger.warning(
            "documents: миграция auto_vacuum на %s заняла %.3f с (VACUUM унаследованной БД, писатели ждали столько же)",
            db_path,
            float(outcome.get("duration_sec", 0.0)),
        )
    elif mode == 0:
        _logger.warning(
            "documents: %s остался с auto_vacuum=0 без отказа — PRAGMA проигнорирована молча; "
            "удаление документов не уменьшит файл",
            db_path,
        )
    return mode
