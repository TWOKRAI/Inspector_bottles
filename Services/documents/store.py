# -*- coding: utf-8 -*-
"""``DocumentStore`` — реализация плоскости документов поверх ``Services/sql``.

Своего движка, пула и DDL здесь нет: таблицу и индексы собирает ``DDLBuilder`` из
``SQLMeta`` схемы, вставку делает ``GenericRepository``, доменные запросы (ORDER BY /
LIMIT / DELETE по времени) идут через адаптер — ровно как в ``action_log``.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from Services.sql.core.base_repository import GenericRepository
from Services.sql.core.ddl_builder import DDLBuilder
from Services.sql.interfaces import ISyncEngineAdapter

from .schema import DocumentRow, from_document_row, to_document_row

__all__ = ["DocumentStore"]

_TABLE = "documents"


class DocumentStore:
    """Долговечное хранилище документов со сроком хранения ПО ВРЕМЕНИ.

    Реализует ``IDocumentStore`` (и тем самым ``IDocumentSink``) — см.
    :mod:`Services.documents.interfaces`, там же контракт Pre/Post и обоснование границ.
    """

    def __init__(
        self,
        adapter: ISyncEngineAdapter,
        retention_sec: Optional[Dict[str, float]] = None,
        *,
        clock: Callable[[], float] = time.time,
        dialect: str = "sqlite",
    ) -> None:
        """
        Args:
            adapter: синхронный адаптер движка БД.
            retention_sec: срок хранения per-kind в секундах. Род, которого здесь нет,
                НЕ удаляется никогда — молчание конфига не является разрешением потерять
                документ о качестве. ``None`` → не удаляется ничего.
            clock: источник времени. Зависимость, а не глобальный вызов: иначе тест
                смог бы задать время только патчем модуля ``time``, то есть для всего
                процесса.
            dialect: диалект для DDL.
        """
        self._adapter = adapter
        self._retention = dict(retention_sec or {})
        self._now = clock
        self._dialect = dialect
        # Сериализация записи: sqlite-соединение не потокобезопасно при общем
        # использовании, а писателей у плоскости минимум два (аудит из потока команд
        # и вердикты с линии).
        self._lock = threading.RLock()
        #: Отказы записи. Терять документ можно (сбой БД не должен ронять линию),
        #: молчать о потере — нельзя.
        self.dropped = 0
        #: Сколько страниц ретеншен вернул ОС за жизнь стора. Без этого числа
        #: «файл уменьшился» пришлось бы доказывать размером файла, а он меняется
        #: и от записи соседа (3.1).
        self.pages_reclaimed = 0
        #: Отказы возврата страниц. Уборка не удалась — документы всё равно удалены,
        #: и это не повод ронять такт heartbeat; но и не повод молчать.
        self.reclaim_failed = 0

        self._repo = GenericRepository(adapter=adapter, schema_class=DocumentRow, id_column="doc_id")
        self._ensure_schema(dialect)

    def _ensure_schema(self, dialect: str) -> None:
        """Создать таблицу и индексы, если их нет (idempotent)."""
        from Services.sql.adapters.schema_mapper import SchemaBaseMapper

        for stmt in DDLBuilder(SchemaBaseMapper()).build_create_table(DocumentRow, dialect=dialect):
            self._adapter.execute(stmt)

    # ------------------------------------------------------------------
    # IDocumentSink
    # ------------------------------------------------------------------

    def append(self, document: Dict[str, Any]) -> bool:
        """Записать документ. См. контракт в ``interfaces.IDocumentSink.append``."""
        try:
            kind = document["kind"]
            ts = document["ts"]
        except (KeyError, TypeError):
            self.dropped += 1
            return False
        if not isinstance(kind, str) or not kind:
            self.dropped += 1
            return False

        try:
            row = to_document_row({**document, "kind": kind, "ts": float(ts)}, doc_id=uuid.uuid4().hex)
        except (TypeError, ValueError):
            self.dropped += 1
            return False

        try:
            with self._lock:
                self._repo.insert(row)
            return True
        except Exception:  # noqa: BLE001 — сбой хранилища не имеет права уронить писателя
            # Исключение наружу не выходит по контракту: append зовётся из пути смены
            # конфигурации и с линии. Потеря названа счётчиком, а не молчанием.
            self.dropped += 1
            return False

    # ------------------------------------------------------------------
    # IDocumentStore
    # ------------------------------------------------------------------

    def query(
        self,
        kind: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Страница документов, свежие первыми. Контракт — в ``interfaces``."""
        if limit <= 0:
            raise ValueError("limit обязан быть > 0")
        if offset < 0:
            raise ValueError("offset обязан быть >= 0")

        clauses: List[str] = []
        params: Dict[str, Any] = {}
        if kind is not None:
            clauses.append('"kind" = :kind')
            params["kind"] = kind
        if since is not None:
            clauses.append('"ts" >= :since')
            params["since"] = float(since)
        if until is not None:
            clauses.append('"ts" <= :until')
            params["until"] = float(until)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params["limit"] = int(limit)
        params["offset"] = int(offset)
        sql = f'SELECT * FROM "{_TABLE}"{where} ORDER BY "ts" DESC LIMIT :limit OFFSET :offset'  # nosec B608

        with self._lock:
            rows = self._adapter.query(sql, params)
        return [from_document_row(DocumentRow.model_validate(r)) for r in rows]

    def purge_expired(self, now: Optional[float] = None) -> int:
        """Удалить документы с истёкшим сроком. Контракт — в ``interfaces``."""
        moment = self._now() if now is None else float(now)
        removed = 0
        with self._lock:
            for kind, ttl in self._retention.items():
                if ttl is None or ttl <= 0:
                    # Срок 0/отрицательный трактуем как «не задан», а не «удалить всё»:
                    # опечатка в конфиге не должна стирать документы о качестве.
                    continue
                sql = f'DELETE FROM "{_TABLE}" WHERE "kind" = :kind AND "ts" < :cutoff'  # nosec B608
                removed += int(self._adapter.execute(sql, {"kind": kind, "cutoff": moment - float(ttl)}) or 0)
        if removed:
            self._reclaim_free_pages()
        return removed

    def _reclaim_free_pages(self) -> None:
        """Отдать ОС страницы, освободившиеся после удаления документов.

        **Почему это часть ретеншена, а не отдельная забота.** ``DELETE`` в SQLite не
        уменьшает файл: страницы уходят во freelist и ждут новых строк. Ретеншен, который
        удаляет документы и не возвращает байты, выполняет свою букву и не выполняет
        смысла — «приёмник не пухнет». Замер (2026-08-11): 20 000 строк, удалено 95 % —
        файл 8.71 МиБ до возврата страниц и 0.44 МиБ после.

        Вне ``self._lock``: работа идёт на своём соединении, наш замок сериализует только
        наши записи, а держать его на время уборки значило бы блокировать писателей линии
        дольше, чем это делает сам SQLite.

        Отсутствие способности у адаптера — не отказ: PostgreSQL/MySQL сами управляют
        своим хозяйством, и звать их нечем. Проверка та же, что у :meth:`close` с
        ``dispose``.
        """
        if self._dialect != "sqlite":
            return
        reclaim = getattr(self._adapter, "incremental_vacuum", None)
        if not callable(reclaim):
            return
        try:
            self.pages_reclaimed += int(reclaim())
        except Exception:  # noqa: BLE001 — документы уже удалены; такт уборки ронять нельзя
            self.reclaim_failed += 1

    def close(self) -> None:
        """Освободить движок БД (graceful teardown процесса).

        Симметрия с ``ObservabilityStore.close`` не косметическая: на Windows
        неотпущенный файл БД не даёт удалить каталог, и тест, забывший закрыть стор,
        падает не там, где ошибся, а в уборке ``tmp_path``.
        """
        dispose = getattr(self._adapter, "dispose", None)
        if callable(dispose):
            dispose()

    def count(self, kind: Optional[str] = None) -> int:
        """Число документов (опц. по роду) — для проб и вкладки."""
        where = ' WHERE "kind" = :kind' if kind is not None else ""
        params = {"kind": kind} if kind is not None else {}
        sql = f'SELECT COUNT(*) AS cnt FROM "{_TABLE}"{where}'  # nosec B608
        with self._lock:
            rows = self._adapter.query(sql, params)
        return int(rows[0].get("cnt", 0)) if rows else 0
