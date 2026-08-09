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
без дубля): общие колонки (kind/process/module/ts/severity/message) + JSON `extra`
со всем остальным (для stats severity=metric_type, message=metric). Колонка
`process` (5.21 (c)) — имя процесса-источника, для старых БД доливается ALTER'ом.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from .record_display import hub_record_to_display

KIND_LOG = "log"
KIND_ERROR = "error"
KIND_STATS = "stats"


def resolve_default_db_path() -> str:
    """Путь к файлу стора по умолчанию: <log_dir>/observability.db.

    log_dir — из env INSPECTOR_LOG_DIR / MULTIPROCESS_LOG_DIR, иначе "logs".
    """
    log_dir = os.environ.get("INSPECTOR_LOG_DIR") or os.environ.get("MULTIPROCESS_LOG_DIR") or "logs"
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
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_kind_id ON records(kind, id)")
            # Ф3.6: индекс под пороговый запрос «всё от WARNING и выше». Без него
            # выигрыш числа перед membership-фильтром по строкам был бы только
            # выразительным, но не быстрым.
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_severity_number ON records(severity_number, id)")
            self._conn.commit()

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
                    "(kind, process, module, ts, severity, severity_number, message, extra) "
                    "VALUES (:kind, :process, :module, :ts, :severity, :severity_number, :message, :extra)",
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

    def list_records(
        self,
        kind: Optional[str] = None,
        module: Optional[str] = None,
        severity_in: Optional[List[str]] = None,
        min_severity: Optional[int] = None,
        offset: int = 0,
        limit: int = 100,
        newest_first: bool = True,
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

        Returns:
            Список dict-строк: {id,kind,module,ts,severity,message,extra(dict)}.
        """
        clauses: List[str] = []
        params: List[Any] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if module is not None:
            clauses.append("module = ?")
            params.append(module)
        if severity_in:
            placeholders = ",".join("?" for _ in severity_in)
            clauses.append(f"severity IN ({placeholders})")
            params.extend(s.lower() for s in severity_in)
        if min_severity is not None:
            # Ф3.6: ПОРОГ, а не членство. Раньше «покажи всё от WARNING и выше»
            # выражалось только перечислением уровней вручную, и новый уровень
            # в такой список никто бы не добавил.
            clauses.append("severity_number >= ?")
            params.append(int(min_severity))

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = "DESC" if newest_first else "ASC"
        # Подстановки в SQL ниже НЕ пользовательские: `where` собран из
        # ЛИТЕРАЛЬНЫХ кусков выше, `order` принимает два значения из bool.
        # Все значения фильтров (kind/module/severity/min_severity/limit/offset)
        # уходят через `?`-плейсхолдеры в `params`. Предупреждение было в этом
        # файле и до Ф3.6 — хук сканирует только изменённые файлы, поэтому
        # всплыло при первой же правке стора.
        sql = (
            "SELECT id, kind, process, module, ts, severity, severity_number, message, extra FROM records"
            f"{where} ORDER BY id {order} LIMIT ? OFFSET ?"  # nosec B608
        )
        params.extend([int(limit), int(offset)])

        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = cur.fetchall()
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
