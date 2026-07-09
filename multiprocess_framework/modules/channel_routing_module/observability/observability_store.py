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

Нормализация в строку: общие колонки (kind/module/ts/severity/message) + JSON
`extra` со всем остальным (для stats severity=metric_type, message=metric).
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

KIND_LOG = "log"
KIND_ERROR = "error"
KIND_STATS = "stats"


def resolve_default_db_path() -> str:
    """Путь к файлу стора по умолчанию: <log_dir>/observability.db.

    log_dir — из env INSPECTOR_LOG_DIR / MULTIPROCESS_LOG_DIR, иначе "logs".
    """
    log_dir = os.environ.get("INSPECTOR_LOG_DIR") or os.environ.get("MULTIPROCESS_LOG_DIR") or "logs"
    return os.path.join(log_dir, "observability.db")


def _row_from_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Нормализовать hub-запись в строку таблицы (kind/module/ts/severity/message/extra)."""
    kind = record.get("kind", "")
    module = record.get("module", "")
    ts = float(record.get("ts", 0.0) or 0.0)

    if kind == KIND_STATS:
        severity = record.get("metric_type", "")
        message = record.get("metric", "")
        extra = {"value": record.get("value"), "tags": record.get("tags", {})}
    else:
        severity = record.get("severity", "")
        message = record.get("message", "")
        # Всё, кроме конвертных полей, уносим в extra (error_type/traceback/context).
        extra = {k: v for k, v in record.items() if k not in ("kind", "module", "ts", "severity", "message")}

    return {
        "kind": kind,
        "module": module,
        "ts": ts,
        "severity": severity,
        "message": message,
        "extra": json.dumps(extra, ensure_ascii=False, default=str),
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
                    module   TEXT NOT NULL,
                    ts       REAL NOT NULL,
                    severity TEXT,
                    message  TEXT,
                    extra    TEXT
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_records_kind_id ON records(kind, id)")
            self._conn.commit()

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
                    "INSERT INTO records (kind, module, ts, severity, message, extra) "
                    "VALUES (:kind, :module, :ts, :severity, :message, :extra)",
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

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = "DESC" if newest_first else "ASC"
        sql = (
            f"SELECT id, kind, module, ts, severity, message, extra FROM records"
            f"{where} ORDER BY id {order} LIMIT ? OFFSET ?"
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
            "module": row["module"],
            "ts": row["ts"],
            "severity": row["severity"],
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
