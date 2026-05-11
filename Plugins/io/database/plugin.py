"""DatabasePlugin -- хранение результатов обработки в SQLite.

Output-плагин: process(items) -> items (pass-through с side-effect записи в БД).
Batch INSERT по таймеру или по count.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin
from multiprocess_framework.modules.process_module.plugins import ExecutionMode, ThreadConfig

from .registers import DatabaseRegisters


@register_plugin("database", category="output", description="Запись результатов в SQLite")
class DatabasePlugin(ProcessModulePlugin):
    """Batch-запись результатов обработки в SQLite."""

    name = "database"
    category = "output"

    inputs = [
        Port(name="result", dtype="dict", shape="(*,)", description="Результат обработки"),
    ]
    outputs = []

    commands = {
        "flush": "_cmd_flush",
        "get_stats": "_cmd_get_stats",
        "set_batch_size": "_cmd_set_batch_size",
        "reset_stats": "_cmd_reset_stats",
    }
    register_class = DatabaseRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        self._buffer: list[dict] = []
        self._buffer_lock = threading.Lock()
        self._total_written: int = 0
        self._total_errors: int = 0

        # Создаём директорию
        db_file = Path(self._reg.db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

        ctx.log_info(
            f"DatabasePlugin: db={self._reg.db_path}, "
            f"batch={self._reg.batch_size}, flush_interval={self._reg.flush_interval_sec}s"
        )

    def start(self, ctx: PluginContext) -> None:
        """Открыть соединение, создать таблицу, запустить flush worker."""
        self._conn = sqlite3.connect(self._reg.db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS detections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                frame_id INTEGER,
                camera_id INTEGER,
                event_type TEXT,
                data TEXT,
                created_at REAL DEFAULT (unixepoch('now'))
            )
        """)
        self._conn.commit()

        # Worker для периодического flush (фоновая задача, не data flow)
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "db_flush_worker", self._flush_loop, cfg, auto_start=True
        )
        ctx.log_info("DatabasePlugin: started, таблица detections готова")

    def shutdown(self, ctx: PluginContext) -> None:
        """Flush остатков и закрытие соединения."""
        self._flush_buffer()
        if self._conn:
            self._conn.close()
            self._conn = None
        ctx.log_info(f"DatabasePlugin: shutdown, всего записано: {self._total_written}")

    def process(self, items: list[dict]) -> list[dict]:
        """Записать items в буфер для batch INSERT. Pass-through."""
        for item in items:
            self._add_to_buffer(item, item.get("event_type", "frame_processed"))
        return items

    # --- Буферизация ---

    def _add_to_buffer(self, data: dict, event_type: str) -> None:
        """Добавить запись в буфер."""
        record = {
            "timestamp": data.get("timestamp", time.time()),
            "frame_id": data.get("frame_id", 0),
            "camera_id": data.get("camera_id", 0),
            "event_type": event_type,
            "data": str(data),
        }
        with self._buffer_lock:
            self._buffer.append(record)
            if len(self._buffer) >= self._reg.batch_size:
                # Забираем batch прямо здесь (lock уже захвачен) и сбрасываем
                batch = self._buffer[:]
                self._buffer.clear()
                self._do_flush(batch)

    def _flush_loop(self, stop_event, pause_event) -> None:
        """Периодический flush буфера."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self._reg.flush_interval_sec)
            self._flush_buffer()

    def _flush_buffer(self) -> int:
        """Записать буфер в БД (захватывает lock)."""
        with self._buffer_lock:
            if not self._buffer:
                return 0
            batch = self._buffer[:]
            self._buffer.clear()

        return self._do_flush(batch)

    def _do_flush(self, batch: list[dict]) -> int:
        """Записать готовый batch в БД (без захвата lock)."""

        if not self._conn:
            return 0

        insert_sql = (
            "INSERT INTO detections (timestamp, frame_id, camera_id, event_type, data) "
            "VALUES (:timestamp, :frame_id, :camera_id, :event_type, :data)"
        )
        try:
            self._conn.executemany(insert_sql, batch)
            self._conn.commit()
            count = len(batch)
            self._total_written += count
            return count
        except Exception as e:
            # Fallback: вставляем по одной записи
            self._ctx.log_error(f"Batch insert failed: {e}, trying one-by-one")
            saved = 0
            for record in batch:
                try:
                    self._conn.execute(insert_sql, record)
                    saved += 1
                except Exception:
                    self._total_errors += 1
            if saved > 0:
                self._conn.commit()
            count = saved
            self._total_written += count
            return count

    # --- Команды ---

    def _cmd_flush(self, data: dict) -> dict:
        """Принудительный flush буфера."""
        count = self._flush_buffer()
        return {"status": "ok", "flushed": count, "total": self._total_written}

    def _cmd_get_stats(self, data: dict) -> dict:
        """Статистика."""
        with self._buffer_lock:
            pending = len(self._buffer)
        return {
            "status": "ok",
            "total_written": self._total_written,
            "total_errors": self._total_errors,
            "pending": pending,
            "db_path": self._reg.db_path,
        }

    def _cmd_set_batch_size(self, data: dict) -> dict:
        """Изменить размер batch на лету."""
        size = max(1, min(10000, int(data.get("batch_size", self._reg.batch_size))))
        self._reg.batch_size = size
        return {"status": "ok", "batch_size": self._reg.batch_size}

    def _cmd_reset_stats(self, data: dict) -> dict:
        """Обнулить счётчики total_written и total_errors."""
        self._total_written = 0
        self._total_errors = 0
        return {"status": "ok"}
