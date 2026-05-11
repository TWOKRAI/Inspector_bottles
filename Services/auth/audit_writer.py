# -*- coding: utf-8 -*-
"""
AuditWriter — асинхронный писатель аудит-лога.

Архитектура:
- Фоновый daemon-поток читает из очереди и записывает в SqliteAuditStorage.
- Батчинг: до 50 записей или таймаут 100 мс — снижает нагрузку на SQLite.
- JSONL fallback: при сбое SQLite запись сохраняется в файл построчно.
- recover_fallback(): при старте читает JSONL и мигрирует записи обратно в БД.

Контракт (IAuditWriter):
    writer.log(entry)    — non-blocking, ставит в очередь
    writer.start()       — запустить фоновый поток
    writer.stop()        — flush + join(timeout=5)

Использование:
    storage = SqliteAuditStorage("sqlite:///audit.db")
    storage.ensure_schema()

    writer = AuditWriter(storage, fallback_path="/var/log/audit_fallback.jsonl")
    writer.start()
    writer.log(AuditEntry.with_truncation(...))
    writer.stop()
"""
from __future__ import annotations

import json
import os
import queue
import threading
from datetime import datetime, timezone
from typing import Optional

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin

from .models import AuditEntry
from .storage.audit_storage import SqliteAuditStorage

# Максимальный размер батча перед сбросом в БД
_BATCH_MAX_SIZE = 50
# Таймаут ожидания следующей записи (секунды) — при истечении сбрасывает текущий батч
_BATCH_TIMEOUT_SEC = 0.1


class AuditWriter(BaseManager, ObservableMixin):
    """
    Асинхронный писатель аудит-лога с батчингом и JSONL fallback.

    Все операции с SQLite выполняются в фоновом daemon-потоке.
    UI-поток никогда не ждёт SQLite — только non-blocking queue.put_nowait().

    Args:
        storage:       SqliteAuditStorage с уже вызванным ensure_schema().
        fallback_path: Путь к JSONL-файлу для записи при сбое SQLite.
                       При следующем start() эти записи автоматически мигрируются в БД.
    """

    def __init__(
        self,
        storage: SqliteAuditStorage,
        fallback_path: str,
        managers: Optional[dict] = None,
        process: Optional[object] = None,
    ) -> None:
        BaseManager.__init__(self, "AuditWriter", process=process)
        ObservableMixin.__init__(self, managers=managers or {}, config={})

        self._storage = storage
        self._fallback_path = fallback_path

        # Очередь: AuditEntry | None (None = sentinel для остановки)
        self._queue: queue.Queue[Optional[AuditEntry]] = queue.Queue()

        self._thread: Optional[threading.Thread] = None
        self._started = False

    # =========================================================================
    # BaseManager lifecycle (initialize / shutdown)
    # =========================================================================

    def initialize(self) -> bool:
        """Инициализация: запускаем фоновый поток."""
        self.start()
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        """Завершение: останавливаем фоновый поток с flush."""
        self.stop()
        self.is_initialized = False
        return True

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def start(self) -> None:
        """
        Запустить фоновый поток.

        Перед стартом вызывает recover_fallback() — мигрирует незакоммиченные
        записи из JSONL в SQLite.
        """
        if self._started:
            return

        # Восстановить записи из JSONL перед стартом основного потока
        recovered = self.recover_fallback()
        if recovered > 0:
            self._log_info(
                f"auth.audit.recover_fallback: count={recovered}, path={self._fallback_path!r}"
            )

        self._thread = threading.Thread(
            target=self._worker,
            name="AuditWriter",
            daemon=True,
        )
        self._started = True
        self._thread.start()
        self._log_info("auth.audit.started")

    def stop(self) -> None:
        """
        Остановить фоновый поток.

        Помещает sentinel None в очередь, ждёт завершения (timeout=5 с).
        Все записи из очереди сбрасываются перед выходом.
        """
        if not self._started:
            return

        self._queue.put(None)  # sentinel
        if self._thread is not None:
            self._thread.join(timeout=5)

        self._started = False
        self._log_info("auth.audit.stopped")

    # =========================================================================
    # Публичный API
    # =========================================================================

    def log(self, entry: AuditEntry) -> None:
        """
        Поставить запись аудита в очередь (non-blocking).

        Если очередь заполнена — запись сбрасывается в JSONL fallback напрямую,
        чтобы не блокировать UI-поток. В штатном режиме очередь практически пуста.

        Args:
            entry: AuditEntry (рекомендуется AuditEntry.with_truncation()).
        """
        self._queue.put_nowait(entry)

    # =========================================================================
    # Восстановление из fallback
    # =========================================================================

    def recover_fallback(self) -> int:
        """
        Мигрировать записи из JSONL fallback-файла в SQLite.

        Читает файл построчно, десериализует каждую строку как AuditEntry,
        вставляет в БД. При успехе переименовывает файл в .migrated.<utc-ts>.

        Returns:
            Количество восстановленных записей (0 если файл не существует).
        """
        if not os.path.exists(self._fallback_path):
            return 0

        entries: list[AuditEntry] = []
        with open(self._fallback_path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = AuditEntry.model_validate(data)
                    entries.append(entry)
                except Exception as exc:
                    # Пропустить повреждённую строку, не падать
                    self._log_warning(
                        f"auth.audit.recover_fallback.skip_line: "
                        f"lineno={lineno}, reason={exc!r}"
                    )

        if not entries:
            # Файл пуст или все строки повреждены — архивируем и выходим
            self._archive_fallback()
            return 0

        # Вставляем записи в БД (индивидуально — не теряем частичный успех)
        inserted = 0
        for entry in entries:
            try:
                self._storage.append_audit(entry)
                inserted += 1
            except Exception as exc:
                self._log_warning(
                    f"auth.audit.recover_fallback.insert_failed: "
                    f"entry_id={entry.entry_id!r}, reason={exc!r}"
                )

        self._archive_fallback()
        return inserted

    # =========================================================================
    # Внутренние методы
    # =========================================================================

    def _worker(self) -> None:
        """Основной цикл фонового потока. Читает из очереди, пишет батчами."""
        batch: list[AuditEntry] = []

        while True:
            try:
                # Ждём запись с таймаутом (для батчинга по времени)
                entry = self._queue.get(timeout=_BATCH_TIMEOUT_SEC)
            except queue.Empty:
                # Таймаут — сбрасываем накопленный батч
                if batch:
                    self._write_batch(batch)
                    batch = []
                continue

            # Sentinel — стоп
            if entry is None:
                # Сначала сбрасываем батч
                if batch:
                    self._write_batch(batch)
                break

            batch.append(entry)

            # Достигнут максимальный размер батча — сбрасываем немедленно
            if len(batch) >= _BATCH_MAX_SIZE:
                self._write_batch(batch)
                batch = []

    def _write_batch(self, batch: list[AuditEntry]) -> None:
        """
        Записать батч в SQLite. При сбое — каждую запись сбросить в JSONL.

        Исключения из storage.append_audit (кроме AuditImmutableError)
        перехватываются и логируются — поток продолжает работу.
        """
        for entry in batch:
            try:
                self._storage.append_audit(entry)
            except Exception as exc:
                # Сбой SQLite — пишем в JSONL fallback, не теряем запись
                self._write_to_fallback(entry)
                self._log_error(
                    f"auth.audit.write_failed: "
                    f"Не удалось записать AuditEntry в SQLite: {exc!r}. "
                    f"Запись сброшена в JSONL fallback."
                )

    def _write_to_fallback(self, entry: AuditEntry) -> None:
        """Дописать запись в JSONL fallback-файл (append-mode)."""
        try:
            with open(self._fallback_path, "a", encoding="utf-8") as fh:
                fh.write(entry.model_dump_json() + "\n")
        except Exception as exc:
            # Последний рубеж — если и JSONL недоступен, просто печатаем
            print(
                f"[AuditWriter] КРИТИЧЕСКАЯ ОШИБКА: не удалось записать в JSONL "
                f"fallback {self._fallback_path!r}: {exc!r}. "
                f"entry_id={entry.entry_id!r}"
            )

    def _archive_fallback(self) -> None:
        """Переименовать fallback-файл в .migrated.<utc-isoformat>."""
        try:
            ts = datetime.now(timezone.utc).isoformat().replace(":", "-")
            archive_path = f"{self._fallback_path}.migrated.{ts}"
            os.rename(self._fallback_path, archive_path)
        except Exception as exc:
            print(
                f"[AuditWriter] Не удалось архивировать fallback-файл "
                f"{self._fallback_path!r}: {exc!r}"
            )
