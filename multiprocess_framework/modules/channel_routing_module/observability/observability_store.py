# -*- coding: utf-8 -*-
"""
ObservabilityStore — персистентный стор записей наблюдаемости (Ф5.20a).

ObservabilityHub (Ф5.15) — эфемерный in-memory буфер: после drain записи живут
лишь в реальных менеджерах-sink'ах (файловый лог), запросить «всю историю»
нельзя. Стор закрывает это: drain-петля ProcessModule (Ф5.16) сливает
дренированные записи не только в sink'и (adapter), но и сюда — SQLite-файл,
переживающий рестарт процесса. GUI-вкладки Логи/Ошибки/Статистика (Ф5.19)
читают целую историю пагинацией (list_records), живой хвост идёт отдельным
каналом hub→GUI (Ф5.20b), не через стор.

Аналог `SqliteAuditStorage` (Services/auth), но:
  - stdlib `sqlite3` (без SQLAlchemy) — стор в framework-слое, лишних зависимостей нет;
  - одна таблица `records` на три kind (log/error/stats) — фильтр по kind/severity;
  - WAL + busy_timeout: писатель — КАЖДЫЙ ProcessModule (свой процесс), читатель —
    GUI; общий файл выдерживает конкурентную запись нескольких процессов.

Формат записи на входе (append_records) — dict из ObservabilityHub.drain_*:
  log:   {kind:'log',   module, ts, severity, message, context}
  error: {kind:'error', module, ts, severity, error_type, message, traceback, context}
  stats: {kind:'stats', module, ts, metric, value, metric_type, tags}

Нормализация в строку — ЕДИНЫМ ``record_display.hub_record_to_display`` (5.21 (b),
без дубля): общие колонки (kind/process/module/ts/severity/metric/message) + JSON
`extra` со всем остальным. Колонка `process` (5.21 (c)) — имя процесса-источника,
колонка `metric` (Task 3.1) — полное имя метрики (``capture.drops``) у строк,
которые ЕСТЬ одно число, и NULL у агрегата окна / лога / ошибки; для старых БД обе
доливаются ALTER'ом.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from ..._fallback import emergency_log
from .record_display import hub_record_to_display

KIND_LOG = "log"
KIND_ERROR = "error"
KIND_STATS = "stats"

#: Имя stdlib-логгера аварийного выхода (тот же приём, что в
#: ``channel_routing_manager.py`` — «пишем в stdlib напрямую, никогда через
#: менеджер», 2.2). Стор не может отчитаться о собственной миграции через
#: свою же плоскость наблюдаемости: в момент миграции он ещё открывается.
_EMERGENCY_NAME = __name__

#: Целевая версия схемы для миграции auto_vacuum (D3). Хранится в
#: ``PRAGMA user_version`` файла — так «однократность» переживает рестарт
#: процесса-владельца без отдельной таблицы метаданных.
_AUTO_VACUUM_SCHEMA_VERSION = 1

#: Версия схемы после заведения полнотекстового индекса (задача 1.6). Тот же
#: гейт ``user_version``, следующее число — и потому :meth:`_init_fts` зовётся
#: ПОСЛЕ :meth:`_migrate_auto_vacuum`: поставь версию 2 раньше, и миграция
#: auto_vacuum увидела бы ``2 >= 1`` и пропустила себя молча на унаследованном
#: файле. Порядок здесь — не стиль, а условие.
_FTS_SCHEMA_VERSION = 2

#: Версия схемы после заведения колонки ``metric`` (Task 3.1, К5). Тот же гейт
#: ``user_version``, следующее число — и по той же причине, что у FTS,
#: :meth:`_migrate_add_metric` зовётся ПОСЛЕ :meth:`_init_fts`: поставь версию 3
#: раньше, и backfill полнотекстового индекса увидел бы ``3 >= 2`` и пропустил
#: себя молча на унаследованном файле.
_METRIC_SCHEMA_VERSION = 3

#: Имя теневой таблицы полнотекстового индекса.
_FTS_TABLE = "records_fts"


class ObservabilitySearchError(RuntimeError):
    """Поиск не выполнен — с названной причиной (задача 1.6).

    Исключение, а не пустой список: «ничего не нашлось» и «искать нечем/запрос
    непонят» обязаны различаться. Пустой результат на сломанный запрос — ровно
    класс «тихая потеря», из-за которого оператор уходит уверенным, что записей
    нет, тогда как их не искали.
    """


#: Признаки НАМЕРЕННОГО синтаксиса FTS5 в запросе. Двоеточия здесь НЕТ
#: намеренно: колоночный фильтр ``module:seg`` у панели и так есть отдельными
#: полями, а вот «12:30» оператор вставляет из сообщения постоянно.
_FTS_SYNTAX_CHARS = ('"', "*", "(", ")")
_FTS_OPERATORS = frozenset({"AND", "OR", "NOT", "NEAR"})


def fts_query(text: str) -> str:
    """Превратить то, что НАБРАЛ человек, в выражение, понятное FTS5 (задача 1.6).

    **Найдено живым прогоном, а не тестами.** Самый частый жест оператора —
    скопировать кусок прямо из сообщения и вставить в поиск. Почти любой такой
    кусок голый FTS5 отвергает: ``кадр,`` → «syntax error near ","», ``12:30``
    → «no such column: 12», ``camera-0`` → «no such column: 0», ``ROI=1/2`` →
    «syntax error near "="». Отказ был назван (тихой потери нет), но оператору
    от «syntax error near ","» толку ноль — разбор начинается со слова, а слово
    он в поле вставляет, а не изобретает.

    Правило простое и предсказуемое: **обычный текст ищется как есть**, каждое
    слово — точная фраза; power-синтаксис остаётся доступен, но включается
    ЯВНО — кавычками, звёздочкой, скобками или оператором заглавными
    (``a OR b``). Угадывать «а вдруг он имел в виду OR» не пытаемся: молчаливая
    смена смысла запроса хуже отказа.

    Пустых слов не бывает: кусок без единого буквенно-цифрового символа
    (``,``, ``---``) — это НАЗВАННЫЙ отказ, а не «не нашлось».

    Raises:
        ObservabilitySearchError: в запросе нет ни одного слова.
    """
    if any(ch in text for ch in _FTS_SYNTAX_CHARS):
        return text
    tokens = text.split()
    if any(tok in _FTS_OPERATORS for tok in tokens):
        return text
    # Кавычки внутри слова сюда не доходят (они — признак намерения выше),
    # поэтому экранировать нечего: каждое слово оборачивается целиком.
    words = [tok for tok in tokens if any(ch.isalnum() for ch in tok)]
    if not words:
        raise ObservabilitySearchError(f"в запросе «{text}» нет ни одного слова — искать нечего")
    return " ".join(f'"{word}"' for word in words)


def resolve_default_db_path() -> str:
    """Путь к файлу стора по умолчанию: <log_dir>/observability.db.

    log_dir — из env MULTIPROCESS_LOG_DIR / INSPECTOR_LOG_DIR, иначе "logs".
    """
    log_dir = os.environ.get("MULTIPROCESS_LOG_DIR") or os.environ.get("INSPECTOR_LOG_DIR") or "logs"
    return os.path.join(log_dir, "observability.db")


def _column_or(row: sqlite3.Row, name: str, default: Any) -> Any:
    """Значение колонки, ``default`` вместо NULL.

    NULL достижим и штатен: у строк, записанных до Ф3.6, отметки приёма нет и
    быть не может (её ставит чужой процесс — Ф3.4), а число важности им
    засыпает миграция.

    **Обработки «колонки нет вовсе» здесь НЕТ намеренно.** Она была написана и
    снята: слом-инъекция показала, что ветка недостижима — соединение открывает
    :meth:`ObservabilityStore._init_schema`, а он доливает колонки ALTER'ом ДО
    первого чтения. Код, дублирующий гарантию, лежащую ниже, не защищает, а
    прячет: если гарантия однажды сломается, тихий ``default`` скажет «нет
    данных» вместо громкого отказа.
    """
    value = row[name]
    return default if value is None else value


def _row_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Нормализовать hub-запись в строку таблицы (kind/process/module/ts/severity/message/extra).

    Делегирует ЕДИНОМУ нормализатору ``hub_record_to_display`` (5.21 (b) — без
    дубля логики) и сериализует ``extra`` в JSON только здесь, на границе БД.
    """
    d = hub_record_to_display(record)
    return {
        "kind": d["kind"],
        "process": d["process"],
        "module": d["module"],
        "ts": d["ts"],
        "severity": d["severity"],
        # Ф3.6: число берётся из ТОГО ЖЕ нормализатора, а не считается здесь
        # заново — второй способ вычисления разошёлся бы с живым хвостом молча.
        "severity_number": d.get("severity_number", 0),
        # ``observed_ts`` здесь НЕТ — снят Ф5.2 (Б-3). Отметку приёма ставит
        # ПРИЁМНИК (GUI, `stamp_observed`), а в стор пишут ПРОЦЕССЫ-эмитенты:
        # пути не пересекаются, и колонка простояла пустой 0 из 303 016 строк.
        # Заполнить её можно было бы, только сделав приёмник вторым писателем в
        # чужую БД, то есть сломав «один писатель на процесс», ради которого стор
        # так и построен. Задержка живёт там, где известны ОБА конца — в
        # display-виде живого пути.
        "message": d["message"],
        # Task 3.1 (К4). Имя считает ТОТ ЖЕ нормализатор, что и живой хвост
        # (:func:`..number_record.number_metric_identity`) — второй способ
        # вычисления дал бы строку, найденную по тексту и не найденную фильтром
        # по метрике. ``None`` здесь означает «строка не есть одно число»
        # (агрегат/лог/ошибка) и ложится в колонку как SQL NULL.
        "metric": d.get("metric"),
        "extra": json.dumps(d["extra"], ensure_ascii=False, default=str),
    }


class ObservabilityStore:
    """SQLite-стор записей наблюдаемости: append из drain + пагинированное чтение."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        """
        Args:
            db_path: путь к SQLite-файлу. None → resolve_default_db_path().
                ":memory:" допустим (для тестов, но не переживает reopen).
        """
        self._db_path = db_path if db_path is not None else resolve_default_db_path()
        # sqlite3-соединение не thread-safe при общем использовании — сериализуем
        # доступ RLock'ом (drain и возможные диагностические чтения в одном процессе).
        self._lock = threading.RLock()
        # Счётчик потерянных при записи строк (busy_timeout/locked) — терять можно,
        # молчать нельзя (5.20 review #3). Виден через .dropped.
        self._dropped = 0
        if self._db_path not in (":memory:", "") and os.path.dirname(self._db_path):
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        # Полнотекстовый индекс (1.6): доступен не в каждой сборке SQLite, и
        # «искать нечем» обязано иметь имя, а не выглядеть как «ничего не нашлось».
        self._fts_reason: Optional[str] = None
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            # Ф5.2: ПОРЯДОК ЗДЕСЬ ЗНАЧИМ И ПРОВЕРЕН ЗАМЕРОМ. `auto_vacuum`
            # выставляется ПЕРВЫМ — до `journal_mode=WAL` и до создания таблицы.
            # Замер (2026-08-09, две конфигурации подряд на пустых файлах):
            # WAL первым → `PRAGMA auto_vacuum` = 0, то есть режим молча не
            # применился; auto_vacuum первым → 2 (INCREMENTAL). Молча — ключевое
            # слово: SQLite не отказывает, он игнорирует.
            self._conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            # WAL: конкурентная запись нескольких процессов + чтение GUI без блокировки.
            if self._db_path not in (":memory:", ""):
                self._conn.execute("PRAGMA journal_mode=WAL")
                # synchronous=NORMAL: под WAL безопасно (потеря только при OS-crash,
                # не при app-crash) и убирает fsync на КАЖДЫЙ commit → commit ~µs.
                # Критично: append_records зовётся с heartbeat-потока (drain) и с
                # logging-потока (store-tap), fsync-на-commit блокировал бы их и
                # раздувал окно файловой блокировки на shared WAL (5.20 review #3).
                self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA busy_timeout=2000")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind     TEXT NOT NULL,
                    process  TEXT,
                    module   TEXT NOT NULL,
                    ts       REAL NOT NULL,
                    severity TEXT,
                    message  TEXT,
                    extra    TEXT
                )
                """
            )
            self._migrate_add_process()
            self._migrate_add_severity_number()
            self._migrate_add_metric()
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_kind_id ON records(kind, id)")
            # Ф3.6: индекс под пороговый запрос «всё от WARNING и выше». Без него
            # выигрыш числа перед membership-фильтром по строкам был бы только
            # выразительным, но не быстрым.
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_severity_number ON records(severity_number, id)")
            # Task 3.1 (К4): индекс под ряд по метрике («покажи `capture.drops`
            # за последние 10 минут») — ``(metric, ts)``, а не ``(metric, id)``:
            # ряд читают как ВРЕМЕННОЙ, порядок точек задаёт ``ts``.
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_metric_ts ON records(metric, ts)")
            self._conn.commit()
            self._migrate_auto_vacuum()
            # ПОСЛЕ миграции auto_vacuum — см. комментарий у _FTS_SCHEMA_VERSION.
            self._init_fts()
            # ПОСЛЕ _init_fts — см. комментарий у _METRIC_SCHEMA_VERSION.
            self._migrate_backfill_metric()

    def _migrate_auto_vacuum(self) -> None:
        """Разовая миграция унаследованных БД на реально работающий ``auto_vacuum`` (D3).

        ``PRAGMA auto_vacuum=INCREMENTAL`` в начале :meth:`_init_schema` включает
        режим сразу только для НОВОГО (ещё без таблиц) файла. Файлы, рождённые
        ДО фикса Ф5.2/``083b8527`` — там порядок был обратный (``journal_mode=WAL``
        раньше ``auto_vacuum``), и SQLite молча проигнорировал пожелание — уже
        содержат таблицы и данные, и на непустой БД ``PRAGMA auto_vacuum=...``
        не применяется вовсе, только ``VACUUM`` реально меняет режим страниц.

        Гейт — ``PRAGMA user_version`` (не отдельная таблица: метаданные, не
        строка данных). Не по факту «файл маленький/большой», а один раз за
        всё время жизни файла — ``VACUUM`` переписывает БД целиком и блокирует
        писателей, гонять его на каждом открытии недопустимо на горячем пути.

        **Цена, замеренная не на глаз:** синтетическая унаследованная БД,
        200 000 строк, 118.3 МиБ (потолок стора при том же числе строк —
        ~110 МБ по замеру Ф5.2/``083b8527``, тот же порядок величины) —
        ``VACUUM`` занял 1.06 с (2026-08-10, скрипт в scratchpad задачи D3,
        холодный диск, без конкурентных писателей). Дороже, чем commit
        (~µs), но на одну-разовую миграцию при старте процесса-владельца —
        не в ``append_records`` — приемлемо; в горячий путь не попадает.

        ``VACUUM`` транзакционен (или полностью применяется, или файл остаётся
        прежним) и требует свободного места ≈ размера БД — при сбое питания
        посреди него исходные данные не теряются, отдельная защита копированием
        не нужна (см. Приёмку задачи D3).
        """
        if self._db_path in (":memory:", ""):
            return  # temp/in-memory БД теста не переживает reopen — миграция бессмысленна
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if version >= _AUTO_VACUUM_SCHEMA_VERSION:
            return
        mode = self._conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if mode == 0:
            started = time.monotonic()
            self._conn.execute("VACUUM")
            duration = time.monotonic() - started
            emergency_log(
                _EMERGENCY_NAME,
                "WARNING",
                "ObservabilityStore: миграция auto_vacuum на %s заняла %.3f с (VACUUM унаследованной БД)",
                self._db_path,
                duration,
            )
        # PRAGMA не принимает `?`-плейсхолдеры — константа модуля, не пользовательский ввод.
        self._conn.execute(f"PRAGMA user_version = {_AUTO_VACUUM_SCHEMA_VERSION}")
        self._conn.commit()

    def _init_fts(self) -> None:
        """Завести полнотекстовый индекс по тексту записи (задача 1.6, С-2).

        **Зачем.** Данные в ``observability.db`` были, а ходить по ним человеку
        нечем: страница по kind/severity — это лента, а разбор начинается со
        слова («что было про `hikvision`?»). Внешней инфраструктуры (Loki, ELK)
        для этого не заводится — таблица уже здесь.

        **Форма — external content** (``content='records'``): FTS5 хранит только
        индекс и берёт текст из самой таблицы, а не её копию. Иначе каждая
        запись жила бы в файле дважды, и предел стора (Ф5.2) пришлось бы делить
        надвое.

        **Индекс не имеет права пережить свои строки.** Ретеншен (:meth:`purge`)
        и :meth:`clear` удаляют из ``records``; без синхронизации индекс рос бы
        вечно — тот же инцидент 645 МБ, только теневой таблицей. Синхронизация —
        триггерами, а не вызовами из Python: писателей у таблицы несколько
        (drain-петля и store-tap), и «не забыть позвать» в каждом из них — это
        договорённость, а триггер — свойство схемы.

        **UPDATE-триггера нет намеренно:** таблица append-only ПО ИНДЕКСИРУЕМЫМ
        колонкам — ``message``/``module``/``process`` не правятся никогда
        (проверяется тестом ``test_no_update_ever_touches_an_indexed_column``;
        прежняя редакция этого абзаца ссылалась на ``test_the_store_never_updates_
        a_row``, какого в дереве нет — Task 3.1, К6). ``UPDATE`` над НЕ
        индексируемыми колонками законен и уже применяется дважды: засыпка
        ``severity_number`` (Ф3.6) и засыпка ``metric``
        (:meth:`_migrate_backfill_metric`, Task 3.1). Появится правка
        индексируемой колонки — тест покраснеет раньше, чем индекс разойдётся с
        текстом.

        **Отсутствие FTS5 в сборке SQLite — законное состояние**: причина
        запоминается и называется в :meth:`search`, поиск отключается, всё
        остальное работает как прежде.

        **Цена, замеренная не на глаз** (200 000 строк, короткие сообщения):
        backfill унаследованного файла — **0.50 с однократно** при открытии
        (второе открытие — 0 мс, гейт держит); файл 20.14 → 30.27 МиБ,
        то есть **+50 % к размеру**. Это не «накладные расходы», а половина
        предела стора: при потолке 200 000 строк планировать надо от файла с
        индексом. Пропорция зависит от длины сообщений — здесь они короткие,
        и доля индекса тем меньше, чем длиннее текст.
        """
        try:
            self._conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS {_FTS_TABLE} USING fts5("  # nosec B608 — константа модуля
                "message, module, process, "
                "content='records', content_rowid='id')"
            )
            self._conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS records_fts_ai AFTER INSERT ON records BEGIN "  # nosec B608
                f"INSERT INTO {_FTS_TABLE}(rowid, message, module, process) "
                "VALUES (new.id, new.message, new.module, new.process); END"
            )
            self._conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS records_fts_ad AFTER DELETE ON records BEGIN "  # nosec B608
                f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}, rowid, message, module, process) "
                "VALUES ('delete', old.id, old.message, old.module, old.process); END"
            )
            self._conn.commit()
        except sqlite3.OperationalError as exc:
            self._fts_reason = f"полнотекстовый индекс недоступен в этой сборке SQLite: {exc}"
            emergency_log(
                _EMERGENCY_NAME,
                "WARNING",
                "ObservabilityStore: %s — поиск по тексту выключен, чтение истории работает",
                self._fts_reason,
            )
            return

        # Разовый backfill унаследованного файла: триггеры ловят только НОВЫЕ
        # строки, а в уже существующей БД их могут быть сотни тысяч. Гейт — тот
        # же `user_version`, что у миграции auto_vacuum: «однократно за жизнь
        # файла», а не «на каждом открытии».
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        if version >= _FTS_SCHEMA_VERSION:
            return
        rows = int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])
        started = time.monotonic()
        self._conn.execute(f"INSERT INTO {_FTS_TABLE}({_FTS_TABLE}) VALUES('rebuild')")  # nosec B608
        # PRAGMA не принимает `?`-плейсхолдеры — константа модуля, не пользовательский ввод.
        self._conn.execute(f"PRAGMA user_version = {_FTS_SCHEMA_VERSION}")
        self._conn.commit()
        if rows:
            emergency_log(
                _EMERGENCY_NAME,
                "WARNING",
                "ObservabilityStore: построен полнотекстовый индекс по %d строкам за %.3f с (%s)",
                rows,
                time.monotonic() - started,
                self._db_path,
            )

    def _migrate_add_severity_number(self) -> None:
        """Аддитивная миграция Ф3.6: ``severity_number``.

        **``observed_ts`` больше не заводится** (Ф5.2, Б-3): у колонки не было
        писателя — отметку приёма ставит GUI, а в стор пишут процессы-эмитенты.
        В уже существующих файлах колонка остаётся (SQLite не мешает лишней
        колонке, а ``DROP COLUMN`` ради пустого поля — миграция без выгоды);
        просто никто её больше не читает и не пишет.

        По образцу :meth:`_migrate_add_process`: колонки доливаются ALTER'ом,
        идемпотентно, старый файл открывается без потерь.

        **Старые строки ЗАСЫПАЮТСЯ, а не остаются NULL** — и это не украшение.
        Пороговый запрос ``severity_number >= 13`` строки с NULL не вернёт, то
        есть вся история до миграции молча исчезла бы из ответа на «покажи всё
        от WARNING и выше». Тихая потеря истории — ровно то, что фаза запрещает.
        Засыпка делается из УЖЕ ХРАНЯЩЕГОСЯ текста уровня, одним UPDATE — на
        КАЖДОМ открытии, идемпотентно (``WHERE severity_number IS NULL``): гейт
        «только при добавлении колонки» терял историю навсегда при падении
        между ALTER'ом и засыпкой (см. комментарий в теле).

        Строки статистики засыпаются нулём (``UNSPECIFIED``) по ``kind``, а не по
        неудаче сопоставления: в их колонке ``severity`` лежит ``metric_type``,
        и это не уровень, а другой словарь.
        """
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(records)")}
        if "severity_number" not in cols:
            self._conn.execute("ALTER TABLE records ADD COLUMN severity_number INTEGER")
        # Засыпка БЕЗУСЛОВНАЯ (идемпотентность даёт WHERE severity_number IS
        # NULL), а не под гейтом «колонку добавили только что». Гейт держался
        # на допущении, что колонка и числа появляются атомарно, — а sqlite3
        # в legacy-режиме коммитит DDL сразу, UPDATE же ехал в транзакции до
        # ``commit()``. Падение в этом окне оставляло файл «колонка есть,
        # числа NULL» НАВСЕГДА: при следующем открытии гейт видел колонку и
        # засыпку пропускал — дореформенная история молча выпадала из
        # порогового запроса. Репродукция — ревью Ф3 (2026-08-05). На
        # здоровом файле UPDATE — дешёвый no-op по индексу severity_number.
        #
        # Литералы, а не подстановка из SEVERITY_NUMBERS: SQL-выражение —
        # второе место, где числа встречаются, и расхождение с таблицей
        # ловит тест (см. test_backfill_matches_the_live_table).
        self._conn.execute(
            """
            UPDATE records SET severity_number = CASE
                WHEN kind = 'stats'   THEN 0
                WHEN severity = 'debug'    THEN 5
                WHEN severity = 'info'     THEN 9
                WHEN severity = 'warning'  THEN 13
                WHEN severity = 'error'    THEN 17
                WHEN severity = 'critical' THEN 21
                ELSE 0
            END
            WHERE severity_number IS NULL
            """
        )

    def _migrate_add_metric(self) -> None:
        """Аддитивная миграция Task 3.1 (К4/К5), ПЕРВАЯ половина: сама колонка ``metric``.

        Разделена с засыпкой (:meth:`_migrate_backfill_metric`) не для красоты:
        ``ALTER TABLE`` обязан отработать ДО ``CREATE INDEX ... (metric, ts)``
        строкой ниже — на унаследованном файле колонки ещё нет, и индекс по ней
        не создался бы вовсе. Засыпка же обязана идти ПОСЛЕ :meth:`_init_fts`
        (см. :data:`_METRIC_SCHEMA_VERSION`), то есть в другом месте порядка.

        Идемпотентно, тем же приёмом, что :meth:`_migrate_add_process`.
        """
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(records)")}
        if "metric" not in cols:
            self._conn.execute("ALTER TABLE records ADD COLUMN metric TEXT")

    def _migrate_backfill_metric(self) -> None:
        """Аддитивная миграция Task 3.1 (К4/К5), ВТОРАЯ половина: засыпка ``metric``.

        **Засыпка БЕЗУСЛОВНАЯ, гейт — состояние ДАННЫХ, а не «колонку только что
        добавили».** Тот же урок, что записан у :meth:`_migrate_add_severity_number`
        и воспроизведён ревью Ф3: sqlite3 в legacy-режиме коммитит DDL сразу, а
        ``UPDATE`` едет в транзакции до ``commit()``. Падение в этом окне
        оставило бы файл в состоянии «колонка есть, значения NULL» НАВСЕГДА —
        при следующем открытии гейт «колонки не было» видел бы колонку и
        засыпку пропускал, а ``where metric='capture.drops'`` молча не находил бы
        дореформенную историю.

        **Отличие от засыпки ``severity_number``, и оно существенное.** Там
        значение получала КАЖДАЯ строка, и множество ``WHERE severity_number IS
        NULL`` опустошало себя за один проход. Здесь ``NULL`` — законное
        конечное состояние агрегата, лога и ошибки (К4), поэтому голое
        ``WHERE metric IS NULL`` не опустошается никогда: оно переписывало бы
        NULL поверх NULL у всей ленты на КАЖДОМ открытии процесса. Условие
        поэтому двойное — «значения нет И оно вычислимо»; свойство, ради
        которого гейт держится на данных (починка после падения посередине),
        при этом сохраняется полностью.

        **Признак агрегата — ``extra.aggregate``**, тот же
        :data:`..observability_hub.STATS_AGGREGATE_KEY`, что читают нормализатор
        и drain-адаптер. Второй независимый признак того же класса (скажем,
        «текст начинается с ``metrics snapshot``») разошёлся бы с первым молча —
        и разошёлся бы прямо сейчас: у строк, записанных ПОСЛЕ этой задачи,
        ``severity`` у агрегата и у одиночной метрики одинаков (``number``,
        К7), то есть по нему их уже не различить.

        **``json_valid`` перед ``json_extract``, и именно через ``CASE``.**
        ``json_extract`` на непарсимом тексте не возвращает NULL, а роняет
        ``OperationalError`` («malformed JSON»): одна битая строка ``extra``
        (ручная правка файла, обрыв записи) не дала бы открыть стор вовсе.
        ``CASE`` здесь несущий — только он гарантированно не вычисляет ветку,
        которую не выбрал; порядок операндов ``AND`` такой гарантии не даёт.

        **Непрочитанный конверт значит «не знаю», а НЕ «не агрегат».** Первая
        редакция этого условия читала битый ``extra`` как отсутствие маркера
        агрегата, и хазард-тест автора поймал результат: строке-снапшоту
        доставалось имя ``metric = 'metrics snapshot (count=1): fps'`` — ряд по
        такому имени существует, состоит из одной точки и берётся из строки, в
        которой числа нет вовсе. Битая строка остаётся с ``metric IS NULL``:
        видимой недостачей, а не выдуманным именем.

        Отсутствие расширения json1 в сборке SQLite — законное состояние, как и
        отсутствие FTS5: засыпка пропускается с названной причиной в аварийный
        журнал, колонка и всё остальное работают.
        """
        # Версия НЕ поднимается через ступень: :meth:`_init_fts` мог вернуться
        # раньше времени (в сборке нет FTS5) и свою версию 2 не выставить. Скакни
        # мы отсюда сразу на 3 — при следующем открытии уже НА ДРУГОЙ сборке
        # backfill полнотекстового индекса увидел бы ``3 >= 2`` и пропустил себя,
        # оставив индекс пустым для всех прежних строк. Лестница монотонна:
        # ступень 3 берётся только со ступени 2.
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])

        # Литералы ``observation``/``stats`` — те же, что :data:`KIND_STATS` и
        # ``KIND_OBSERVATION``; в SQL они пишутся строкой, как и числа уровней в
        # засыпке ``severity_number``, а сверяет их с живыми константами тест.
        #
        # Предикат «строка ЕСТЬ одно число» написан ОДИН раз и подставляется в
        # обе половины: разойдись ``SET`` и ``WHERE``, засыпка обновляла бы одни
        # строки, а находила другие — то есть писала бы NULL там, где имя есть.
        # ``ELSE 1`` у непрочитанного конверта значит «считаю агрегатом»: не
        # знаю — не называю.
        is_one_number = (
            "(kind = 'observation' AND message <> '') "
            "OR (kind = 'stats' AND message <> '' AND "
            "(CASE WHEN json_valid(extra) THEN json_extract(extra, '$.aggregate') ELSE 1 END) IS NULL)"
        )
        backfill = (
            f"UPDATE records SET metric = CASE WHEN {is_one_number} THEN message ELSE NULL END "  # nosec B608
            f"WHERE metric IS NULL AND ({is_one_number})"
        )
        try:
            self._conn.execute(backfill)
        except sqlite3.OperationalError as exc:
            # json1 отсутствует в сборке (или иная беда SQL): молчать нельзя —
            # «ряд по метрике пуст» иначе читался бы как «данных не было».
            emergency_log(
                _EMERGENCY_NAME,
                "WARNING",
                "ObservabilityStore: засыпка колонки metric на %s не выполнена (%s) — "
                "ряд по имени метрики не увидит записей, сделанных до этой версии",
                self._db_path,
                exc,
            )
            return
        if version >= _FTS_SCHEMA_VERSION:
            # PRAGMA не принимает `?`-плейсхолдеры — константа модуля, не пользовательский ввод.
            self._conn.execute(f"PRAGMA user_version = {_METRIC_SCHEMA_VERSION}")
        self._conn.commit()

    def _migrate_add_process(self) -> None:
        """Аддитивная миграция: колонка ``process`` в старых БД (5.21 (c)).

        CREATE TABLE IF NOT EXISTS не добавляет колонку к уже существующей таблице —
        для файла, созданного до 5.21, доливаем колонку ALTER'ом (nullable, старые
        строки → process=NULL → на чтении падают на ``module``). Идемпотентно.
        """
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(records)")}
        if "process" not in cols:
            self._conn.execute("ALTER TABLE records ADD COLUMN process TEXT")

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    def append_records(self, records: List[Dict[str, Any]]) -> int:
        """Добавить пачку hub-записей. Возвращает число вставленных строк.

        Пустой список — no-op (0). Одна транзакция на пачку (drain по heartbeat).
        """
        if not records:
            return 0
        rows = [_row_from_record(r) for r in records]
        with self._lock:
            try:
                self._conn.executemany(
                    "INSERT INTO records "
                    "(kind, process, module, ts, severity, severity_number, metric, message, extra) "
                    "VALUES (:kind, :process, :module, :ts, :severity, :severity_number, :metric, :message, :extra)",
                    rows,
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                # database is locked / busy_timeout истёк: терять можно, молчать
                # нельзя — считаем потерю (видна через .dropped), не роняем
                # heartbeat/логирование (5.20 review #3).
                self._dropped += len(rows)
                return 0
        return len(rows)

    # ------------------------------------------------------------------
    # Чтение (пагинация — целая история для GUI)
    # ------------------------------------------------------------------

    def _filter_clauses(
        self,
        *,
        kind: Optional[str] = None,
        module: Optional[str] = None,
        process: Optional[str] = None,
        metric: Optional[str] = None,
        severity_in: Optional[List[str]] = None,
        min_severity: Optional[int] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> tuple[List[str], List[Any]]:
        """Собрать WHERE-условия и параметры — ОДИН набор фильтров на оба чтения.

        Общий, а не по копии в :meth:`list_records` и :meth:`search`: две копии
        одного набора расходятся молча, и «фильтр по процессу сузил ленту, но не
        сузил поиск» читалось бы как дефект поиска. Все значения уходят через
        ``?``-плейсхолдеры; в SQL склеиваются только литеральные куски отсюда.

        Имена колонок КВАЛИФИЦИРОВАНЫ псевдонимом ``r``, и оба чтения обязаны
        объявлять ``records r``. Причина найдена прогоном, а не чтением: теневая
        таблица FTS5 несёт колонки с теми же именами (``message``/``module``/
        ``process``), и в соединении неквалифицированное имя даёт
        ``ambiguous column name`` — то есть отказ на КАЖДЫЙ поиск с фильтром.
        """
        clauses: List[str] = []
        params: List[Any] = []
        if kind is not None:
            clauses.append("r.kind = ?")
            params.append(kind)
        if module is not None:
            clauses.append("r.module = ?")
            params.append(module)
        if process is not None:
            clauses.append("r.process = ?")
            params.append(process)
        if metric is not None:
            # Task 3.1 (К4): РЯД по имени метрики. Точное равенство, не LIKE:
            # имена в этой колонке полные (``capture.drops``), а подстрочный
            # фильтр молча склеил бы ряды двух писателей с одинаковым хвостом.
            clauses.append("r.metric = ?")
            params.append(metric)
        if severity_in:
            placeholders = ",".join("?" for _ in severity_in)
            clauses.append(f"r.severity IN ({placeholders})")
            params.extend(s.lower() for s in severity_in)
        if min_severity is not None:
            # Ф3.6: ПОРОГ, а не членство. Раньше «покажи всё от WARNING и выше»
            # выражалось только перечислением уровней вручную, и новый уровень
            # в такой список никто бы не добавил.
            clauses.append("r.severity_number >= ?")
            params.append(int(min_severity))
        if since is not None:
            clauses.append("r.ts >= ?")
            params.append(float(since))
        if until is not None:
            clauses.append("r.ts <= ?")
            params.append(float(until))
        return clauses, params

    def list_records(
        self,
        kind: Optional[str] = None,
        module: Optional[str] = None,
        severity_in: Optional[List[str]] = None,
        min_severity: Optional[int] = None,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = True,
        *,
        process: Optional[str] = None,
        metric: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Вернуть страницу записей (по убыванию id по умолчанию — свежие первыми).

        Args:
            kind: фильтр по kind (log/error/stats) или None (все).
            module: фильтр по модулю-источнику или None.
            severity_in: membership-фильтр по severity — список допустимых значений
                (например ['error','critical']), НЕ порог. None → без фильтра.
                Значения нормализуются в lower-case (severity хранится в нижнем
                регистре), поэтому 'ERROR' и 'error' эквивалентны (5.20 review #7).
            offset/limit: пагинация.
            newest_first: True → ORDER BY id DESC.
            process: фильтр по процессу-источнику (1.6; общий набор с :meth:`search`).
            metric: точное имя метрики (Task 3.1, К4) — ``capture.drops``. Строки
                без имени (агрегат окна, лог, ошибка) в такой срез не попадают
                вовсе: у них колонка NULL, а ``metric = ?`` NULL не равен.
            since/until: окно по ``ts`` (wall-часы писателя), включительно.

        Returns:
            Список dict-строк: {id,kind,process,module,ts,severity,severity_number,
            metric,message,extra(dict)}.
        """
        clauses, params = self._filter_clauses(
            kind=kind,
            module=module,
            process=process,
            metric=metric,
            severity_in=severity_in,
            min_severity=min_severity,
            since=since,
            until=until,
        )
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = "DESC" if newest_first else "ASC"
        # Подстановки в SQL ниже НЕ пользовательские: `where` собран из
        # ЛИТЕРАЛЬНЫХ кусков выше, `order` принимает два значения из bool.
        # Все значения фильтров (kind/module/severity/min_severity/limit/offset)
        # уходят через `?`-плейсхолдеры в `params`. Предупреждение было в этом
        # файле и до Ф3.6 — хук сканирует только изменённые файлы, поэтому
        # всплыло при первой же правке стора.
        sql = (
            "SELECT r.id, r.kind, r.process, r.module, r.ts, r.severity, r.severity_number, r.metric, "
            "r.message, r.extra "
            "FROM records r"
            f"{where} ORDER BY r.id {order} LIMIT ? OFFSET ?"  # nosec B608
        )
        params.extend([int(limit), int(offset)])

        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search(
        self,
        query: str,
        *,
        kind: Optional[str] = None,
        module: Optional[str] = None,
        process: Optional[str] = None,
        metric: Optional[str] = None,
        severity_in: Optional[List[str]] = None,
        min_severity: Optional[int] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = True,
    ) -> List[Dict[str, Any]]:
        """Найти записи по СЛОВУ в тексте (+ те же фильтры, что у ленты) — задача 1.6.

        Ищется по ``message``, ``module`` и ``process``: разбор начинается либо со
        слова из сообщения, либо с имени источника, и заставлять оператора
        выбирать заранее, что он помнит, — лишний вопрос.

        ``query`` — то, что набрал человек: обычный текст ищется как есть
        (каждое слово — точная фраза), power-синтаксис включается явно —
        ``"фраза"``, ``hik*``, ``a OR b``, скобки. Разбор строки — в
        :func:`fts_query`, там же причина: голый FTS5 отвергал почти всё, что
        оператор вставляет из сообщения. Строка уходит параметром, не склейкой;
        непонятый синтаксис остаётся НАЗВАННЫМ отказом.

        Порядок — свежие первыми (``id DESC``), тот же, что у ленты, а не по
        релевантности bm25: панель показывает историю, и «почему эта строка выше
        той» не должно зависеть от того, искал оператор или листал.

        **Цена этого выбора замерена, а не оценена** (200 000 строк, Windows;
        разрешение таймера здесь 15.6 мс, поэтому числа лежат на его сетке —
        меньше одного тика значит «ниже разрешающей способности», а не «ноль»):

        =============================  ==========  ===========
        случай                         FTS5        LIKE-скан
        =============================  ==========  ===========
        редкое слово (1 из 200 000)    < 15.6 мс   16 мс
        отсутствующее слово            < 15.6 мс   31 мс
        частое слово (~1/10 строк)     31 мс       < 15.6 мс
        =============================  ==========  ===========

        Последняя строка — честная цена «свежие первыми»: чтобы отсортировать по
        ``id``, надо собрать ВСЕ совпадения (тут ~20 000), тогда как ``LIKE`` с
        ``LIMIT 100`` останавливается на первой сотне. Выигрыш индекса — там, где
        оператор и ищет: редкое слово и «а было ли вообще», где скан платит
        полным проходом. Менять порядок на bm25 ради частых слов не стали:
        предсказуемость ленты дороже, чем 31 мс на запрос, который и так вернёт
        не то (частое слово — плохой фильтр).

        Raises:
            ObservabilitySearchError: поиск невозможен (нет FTS5 в сборке SQLite)
                или запрос непонят. Пустой список означает ровно «не нашлось» —
                и ничего больше.
        """
        text = str(query or "").strip()
        if self._fts_reason is not None:
            raise ObservabilitySearchError(self._fts_reason)
        if not text:
            raise ObservabilitySearchError("пустой запрос: искать нечего (это не «не нашлось»)")
        text = fts_query(text)

        clauses, params = self._filter_clauses(
            kind=kind,
            module=module,
            process=process,
            metric=metric,
            severity_in=severity_in,
            min_severity=min_severity,
            since=since,
            until=until,
        )
        # Соединение по rowid: external-content FTS5 держит только индекс, текст
        # берётся из самой `records`, поэтому строка ответа — та же, что у ленты.
        where = " AND ".join([f"{_FTS_TABLE} MATCH ?", *clauses])
        order = "DESC" if newest_first else "ASC"
        sql = (
            "SELECT r.id, r.kind, r.process, r.module, r.ts, r.severity, r.severity_number, r.metric, "
            "r.message, r.extra "
            f"FROM {_FTS_TABLE} JOIN records r ON r.id = {_FTS_TABLE}.rowid "  # nosec B608
            f"WHERE {where} ORDER BY r.id {order} LIMIT ? OFFSET ?"  # nosec B608
        )
        args: List[Any] = [text, *params, int(limit), int(offset)]

        with self._lock:
            try:
                rows = self._conn.execute(sql, args).fetchall()
            except sqlite3.OperationalError as exc:
                # Сюда приходит и синтаксическая ошибка запроса FTS5, и отсутствие
                # теневой таблицы. Молчать нельзя: пустой ответ на сломанный
                # запрос читается как «записей нет».
                raise ObservabilitySearchError(f"запрос не понят: {exc}") from exc
        return [self._row_to_dict(r) for r in rows]

    def count(self, kind: Optional[str] = None) -> int:
        """Число записей (опц. по kind)."""
        with self._lock:
            if kind is None:
                cur = self._conn.execute("SELECT COUNT(*) FROM records")
            else:
                cur = self._conn.execute("SELECT COUNT(*) FROM records WHERE kind = ?", (kind,))
            return int(cur.fetchone()[0])

    def purge(
        self,
        *,
        max_rows: Optional[int] = None,
        max_age_sec: Optional[float] = None,
        now: Optional[float] = None,
    ) -> Dict[str, int]:
        """Ретеншен истории: срезать старое по возрасту и по числу строк (Ф5.2).

        **До этой задачи ретеншена не было вовсе** — только ручной :meth:`clear`.
        Пока в стор писал один error-путь, это сходило с рук; с приходом лог-плоскости
        (порог ``observability.history.level``) безлимитная таблица — это инцидент
        645 МБ, повторённый в SQLite. Поэтому предел не опция задачи, а её условие.

        **Две меры, а не одна, и обе нужны.** Возраст отвечает «история за последнюю
        неделю» — предсказуемое окно разбора; число строк отвечает за место на диске
        при всплеске (шторм ошибок за минуту способен переполнить любое окно времени).
        Оставь только возраст — всплеск съест диск; только число — история молча
        схлопнется до последних секунд шторма, и «что было час назад» станет
        неотвечаемым.

        Порядок именно такой: сперва возраст (дешёвый предикат по индексируемому
        ``ts``), потом остаток по числу. Обратный порядок считал бы лимит строк по
        множеству, часть которого всё равно уйдёт по возрасту.

        Args:
            max_rows: сколько СВЕЖИХ строк оставить. ``None``/``<=0`` — не ограничивать.
            max_age_sec: возраст, старше которого строка удаляется. ``None``/``<=0`` —
                не ограничивать. **Ноль значит «предела нет», а не «удалить всё»:**
                мусор в конфиге не должен уметь стирать историю.
            now: показания часов (wall) — параметром, а не ``time.time()`` внутри:
                глобальный патч часов в тестах даёт флейк.

        Returns:
            ``{"by_age": n, "by_rows": m, "remaining": k}`` — сколько чем срезано и
            сколько осталось. Ноль — валидный ответ «резать было нечего».
        """
        by_age = 0
        by_rows = 0
        with self._lock:
            if max_age_sec is not None and float(max_age_sec) > 0:
                moment = time.time() if now is None else float(now)
                cur = self._conn.execute("DELETE FROM records WHERE ts < ?", (moment - float(max_age_sec),))
                by_age = max(0, cur.rowcount)
            if max_rows is not None and int(max_rows) > 0:
                # Граница берётся по `id`, а не по `ts`: часы источников могут идти
                # вразнобой (стор общий на процессы), и срез по времени вырезал бы
                # «свежие» строки процесса с отставшими часами. `id` монотонен по
                # порядку ПРИХОДА в стор — единственная величина, в которой «последние
                # N» имеет один смысл для всех писателей.
                cur = self._conn.execute(
                    "SELECT id FROM records ORDER BY id DESC LIMIT 1 OFFSET ?",
                    (int(max_rows) - 1,),
                )
                row = cur.fetchone()
                if row is not None:
                    cur = self._conn.execute("DELETE FROM records WHERE id < ?", (row[0],))
                    by_rows = max(0, cur.rowcount)
            self._conn.commit()
            # Вернуть освободившиеся страницы ОС. Живая находка 2026-08-09: без
            # этого ретеншен резал СТРОКИ, но не БАЙТЫ — на стенде осталось 2597
            # свободных страниц из 2988 (87 % файла) при 3470 живых строках.
            #
            # ``fetchall()`` здесь **несущий, а не косметика**: ``incremental_vacuum``
            # — шагающий оператор, и ``execute()`` делает ровно ОДИН шаг. Замер:
            # без ``fetchall`` из 99 свободных страниц возвращается 1, с ним —
            # page_count 109 → 10, freelist 0. Первая редакция этой правки была
            # зелёной на глаз и не работала.
            #
            # ``INCREMENTAL``, а не ``FULL``: полный auto_vacuum перекладывает
            # страницы на КАЖДОМ commit'е — плата на горячем пути записи ради
            # уборки, которая нужна раз в пять минут.
            #
            # На БД, созданной до Ф5.2 (режим страниц не заведён), это тихий
            # no-op: файл продолжает переиспользовать свои страницы, то есть
            # ведёт себя как раньше и хуже не становится.
            if by_age or by_rows:
                try:
                    self._conn.execute("PRAGMA incremental_vacuum").fetchall()
                    self._conn.commit()
                except sqlite3.OperationalError:
                    # Уборка места — не то, ради чего можно уронить уборку строк.
                    pass
            remaining = int(self._conn.execute("SELECT COUNT(*) FROM records").fetchone()[0])
            # Свободные страницы — в ответе: «строк 3470, а файл 11.67 МиБ» без этого
            # числа выглядит как поломка учёта, а не как высшая отметка файла.
            free_pages = int(self._conn.execute("PRAGMA freelist_count").fetchone()[0])
        return {"by_age": by_age, "by_rows": by_rows, "remaining": remaining, "free_pages": free_pages}

    def clear(self, kind: Optional[str] = None) -> int:
        """Удалить записи (опц. по kind). Возвращает число удалённых."""
        with self._lock:
            if kind is None:
                cur = self._conn.execute("DELETE FROM records")
            else:
                cur = self._conn.execute("DELETE FROM records WHERE kind = ?", (kind,))
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        try:
            extra = json.loads(row["extra"]) if row["extra"] else {}
        except (ValueError, TypeError):
            extra = {}
        return {
            "id": row["id"],
            "kind": row["kind"],
            # process=NULL в дореформенных строках (миграция 5.21) → падаем на module.
            "process": row["process"] if row["process"] else row["module"],
            "module": row["module"],
            "ts": row["ts"],
            "severity": row["severity"],
            # Дореформенные строки читаются: колонки нет → 0 (UNSPECIFIED), то
            # есть «важность неизвестна», а не «самый низкий уровень».
            "severity_number": _column_or(row, "severity_number", 0),
            # Task 3.1 (К4). Ключ присутствует ВСЕГДА, в том числе значением
            # ``None``: «у этой строки нет имени метрики» и «поле не читали»
            # обязаны различаться, а отсутствующий ключ читается как второе —
            # ``dict.get("metric")`` вернул бы ``None`` в обоих случаях.
            "metric": row["metric"],
            # ``observed_ts`` из ответа снят (Ф5.2, Б-3): у колонки не было писателя
            # и быть не могло. Поле, которое всегда ``None``, читается как «задержки
            # не было», а не как «её здесь не измеряют» — и именно так его читали.
            "message": row["message"],
            "extra": extra,
        }

    @property
    def db_path(self) -> str:
        return self._db_path

    @property
    def dropped(self) -> int:
        """Число строк, потерянных при записи (database locked / busy_timeout)."""
        return self._dropped

    @property
    def search_available(self) -> bool:
        """Есть ли полнотекстовый поиск (задача 1.6). ``False`` — причина в :attr:`search_unavailable_reason`."""
        return self._fts_reason is None

    @property
    def search_unavailable_reason(self) -> Optional[str]:
        """Почему поиска нет, если его нет. ``None`` — поиск доступен.

        Отдельным свойством, а не только исключением из :meth:`search`: панели
        нужно решить, показывать ли строку поиска, ДО первого запроса — иначе
        оператор набирает слово в поле, которое ничего не умеет.
        """
        return self._fts_reason

    def index_rowids(self, term: str) -> List[int]:
        """Что ИНДЕКС думает про слово — напрямую, без соединения с таблицей.

        Единственный способ увидеть остаток индекса, и найден он инъекцией, а не
        рассуждением. Два очевидных способа спросить оказались слепыми:

        * ``SELECT COUNT(*) FROM records_fts`` у external-content таблицы читает
          **саму** ``records``, а не индекс — то есть всегда равен :meth:`count`
          и не может разойтись с ним ПО ПОСТРОЕНИЮ (первая редакция этого метода
          именно так и «сверяла» индекс с таблицей — вакуумно);
        * ``integrity-check`` расхождения тоже не показывает: замер — удаление
          строки без delete-триггера проверку проходит.

        А прямой ``MATCH`` показывает: при работающем триггере слово удалённой
        строки не находится, без него — находится и указывает на мёртвый rowid.
        Наружу такой остаток не протекает (соединение с ``records`` его
        отфильтрует), но он вечен: место занято, а строк нет.

        **Замер, снимающий соблазн «оптимизировать»:** удаление 19 000 строк из
        20 000 даёт ``records_fts_data`` 205 → **259** с триггером и 205 → 205
        без него. То есть удаление в FTS5 — это ЗАПИСЬ надгробия, а не вычитание,
        и файл сразу после уборки временно БОЛЬШЕ. Место возвращает слияние
        сегментов; «индекс сжимается вместе со строками» было бы удобным, но
        неверным утверждением.

        Args:
            term: слово запроса FTS5 (без фильтров — это про индекс, не про ленту).

        Returns:
            rowid'ы, которые индекс относит к этому слову (могут указывать на
            уже удалённые строки — в том и смысл проверки).
        """
        if self._fts_reason is not None:
            return []
        with self._lock:
            cur = self._conn.execute(
                f"SELECT rowid FROM {_FTS_TABLE} WHERE {_FTS_TABLE} MATCH ?",  # nosec B608 — константа модуля
                (str(term),),
            )
            return [int(r[0]) for r in cur.fetchall()]
