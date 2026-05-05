"""DatabasePlugin — хранение результатов детекции в SQLite.

Output-плагин: принимает detection_result / frame_processed →
буферизует → batch INSERT по таймеру или по count.
Лёгкая реализация без SQLManager — прямой sqlite3.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from multiprocess_framework.modules.process_module.plugins.base import (
    PluginContext,
    ProcessModulePlugin,
)
from multiprocess_framework.modules.process_module.plugins.port import Port
from multiprocess_framework.modules.process_module.plugins.registry import register_plugin
from multiprocess_framework.modules.worker_module import ExecutionMode, ThreadConfig


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
        "flush": "flush",
        "get_stats": "get_stats",
    }

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: DB path, batch params, handler."""
        cfg = ctx.config
        self._db_path = cfg.get("db_path", "data/inspector.db")
        self._batch_size: int = cfg.get("batch_size", 100)
        self._flush_interval: float = cfg.get("flush_interval_sec", 2.0)

        # Буфер
        self._buffer: list[dict] = []
        self._buffer_lock = threading.Lock()
        self._total_written: int = 0
        self._last_flush_time: float = time.monotonic()
        self._ctx = ctx

        # Создаём директорию и БД
        db_file = Path(self._db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

        # Handler для входящих результатов
        ctx.router_manager.register_message_handler(
            "detection_result", self._on_detection_result
        )
        ctx.router_manager.register_message_handler(
            "frame_processed", self._on_frame_processed
        )

        # Команды
        ctx.command_manager.register_command("flush", self._cmd_flush)
        ctx.command_manager.register_command("get_stats", self._cmd_get_stats)

        ctx.log_info(
            f"DatabasePlugin: db={self._db_path}, "
            f"batch={self._batch_size}, flush_interval={self._flush_interval}s"
        )

    def start(self, ctx: PluginContext) -> None:
        """Открыть соединение, создать таблицу, запустить flush worker."""
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
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

        # Worker для периодического flush
        cfg = ThreadConfig(execution_mode=ExecutionMode.LOOP)
        ctx.worker_manager.create_worker(
            "db_flush_worker", self._flush_loop, cfg, auto_start=True
        )
        ctx.log_info("DatabasePlugin: started, таблица detections готова")

    def shutdown(self, ctx: PluginContext) -> None:
        """Flush остатков и закрытие соединения."""
        ctx.log_info("DatabasePlugin: shutdown...")
        self._flush_buffer()
        if self._conn:
            self._conn.close()
            self._conn = None
        ctx.log_info(
            f"DatabasePlugin: shutdown complete, всего записано: {self._total_written}"
        )

    # --- Handlers ---

    def _on_detection_result(self, msg: dict) -> None:
        """Handler для detection_result."""
        data = msg.get("data", {})
        self._add_to_buffer(data, "detection")

    def _on_frame_processed(self, msg: dict) -> None:
        """Handler для frame_processed."""
        data = msg.get("data", {})
        self._add_to_buffer(data, "frame_processed")

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
            if len(self._buffer) >= self._batch_size:
                self._flush_buffer()

    # --- Flush ---

    def _flush_loop(self, stop_event, pause_event) -> None:
        """Периодический flush буфера."""
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.1)
                continue
            time.sleep(self._flush_interval)
            self._flush_buffer()

    def _flush_buffer(self) -> int:
        """Записать буфер в БД. Возвращает количество записанных строк."""
        with self._buffer_lock:
            if not self._buffer:
                return 0
            batch = self._buffer[:]
            self._buffer.clear()

        if not self._conn:
            return 0

        try:
            self._conn.executemany(
                "INSERT INTO detections (timestamp, frame_id, camera_id, event_type, data) "
                "VALUES (:timestamp, :frame_id, :camera_id, :event_type, :data)",
                batch,
            )
            self._conn.commit()
            count = len(batch)
            self._total_written += count
            return count
        except Exception as e:
            self._ctx.log_error(f"DatabasePlugin flush error: {e}")
            return 0

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
            "pending": pending,
            "db_path": self._db_path,
        }
