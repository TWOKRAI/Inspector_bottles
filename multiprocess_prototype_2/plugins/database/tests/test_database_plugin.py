"""Тесты DatabasePlugin.

Используем in-memory SQLite и mock PluginContext — без worker_manager.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from multiprocess_prototype_2.plugins.database.plugin import DatabasePlugin


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------

CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS detections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL,
        frame_id INTEGER,
        camera_id INTEGER,
        event_type TEXT,
        data TEXT,
        created_at REAL DEFAULT (unixepoch('now'))
    )
"""


def make_ctx(config: dict | None = None) -> MagicMock:
    """Создать mock PluginContext с заданным config."""
    ctx = MagicMock()
    ctx.config = config or {}
    # log_* — просто no-op
    ctx.log_info = MagicMock()
    ctx.log_error = MagicMock()
    # worker_manager.create_worker — no-op при start()
    ctx.worker_manager.create_worker = MagicMock()
    return ctx


def make_plugin(config: dict | None = None) -> DatabasePlugin:
    """Создать сконфигурированный плагин с in-memory БД."""
    plugin = DatabasePlugin()
    ctx = make_ctx(config)
    plugin.configure(ctx)
    # Подменяем соединение на in-memory после configure, до start
    plugin._conn = sqlite3.connect(":memory:", check_same_thread=False)
    plugin._conn.execute(CREATE_TABLE_SQL)
    plugin._conn.commit()
    return plugin


def count_rows(conn: sqlite3.Connection) -> int:
    """Подсчитать записи в таблице detections."""
    return conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]


# ---------------------------------------------------------------------------
# TestConfigure
# ---------------------------------------------------------------------------

class TestConfigure:
    def test_configure_defaults(self):
        """Параметры по умолчанию парсятся корректно."""
        plugin = DatabasePlugin()
        ctx = make_ctx({})
        plugin.configure(ctx)

        assert plugin._reg.batch_size == 100
        assert plugin._reg.flush_interval_sec == 2.0
        assert plugin._reg.db_path == "data/inspector.db"
        assert plugin._total_written == 0
        assert plugin._total_errors == 0

    def test_configure_custom(self):
        """Пользовательские параметры принимаются."""
        plugin = DatabasePlugin()
        ctx = make_ctx({"batch_size": 50, "flush_interval_sec": 5.0, "db_path": "/tmp/test.db"})
        plugin.configure(ctx)

        assert plugin._reg.batch_size == 50
        assert plugin._reg.flush_interval_sec == 5.0
        assert plugin._reg.db_path == "/tmp/test.db"


# ---------------------------------------------------------------------------
# TestProcess
# ---------------------------------------------------------------------------

class TestProcess:
    def test_process_adds_to_buffer(self):
        """process() добавляет items в буфер."""
        plugin = make_plugin({"batch_size": 100})
        items = [{"frame_id": 1, "timestamp": time.time()}]
        plugin.process(items)

        assert len(plugin._buffer) == 1

    def test_process_pass_through(self):
        """process() возвращает те же items (pass-through)."""
        plugin = make_plugin()
        items = [{"frame_id": 1}, {"frame_id": 2}]
        result = plugin.process(items)

        assert result is items

    def test_batch_flush_on_threshold(self):
        """Когда буфер достигает batch_size — происходит авто-flush."""
        plugin = make_plugin({"batch_size": 3})
        # Добавляем 3 записи — при третьей должен сработать flush
        for i in range(3):
            plugin.process([{"frame_id": i, "timestamp": time.time()}])

        # Буфер должен быть пустым после flush
        assert len(plugin._buffer) == 0
        assert plugin._total_written == 3


# ---------------------------------------------------------------------------
# TestFlush
# ---------------------------------------------------------------------------

class TestFlush:
    def test_flush_writes_to_db(self):
        """_flush_buffer() пишет записи в SQLite."""
        plugin = make_plugin()
        plugin.process([
            {"frame_id": 10, "timestamp": 1.0},
            {"frame_id": 11, "timestamp": 2.0},
        ])
        flushed = plugin._flush_buffer()

        assert flushed == 2
        assert count_rows(plugin._conn) == 2
        assert plugin._total_written == 2

    def test_flush_empty_buffer(self):
        """Flush пустого буфера возвращает 0."""
        plugin = make_plugin()
        result = plugin._flush_buffer()

        assert result == 0
        assert count_rows(plugin._conn) == 0

    def test_fallback_on_batch_error(self):
        """При ошибке executemany — fallback по одной записи."""
        plugin = make_plugin()

        # Добавляем записи напрямую в буфер
        plugin._buffer = [
            {"timestamp": 1.0, "frame_id": 1, "camera_id": 0, "event_type": "test", "data": "{}"},
            {"timestamp": 2.0, "frame_id": 2, "camera_id": 0, "event_type": "test", "data": "{}"},
        ]

        # Ломаем executemany — оборачиваем соединение mock'ом
        real_conn = plugin._conn
        mock_conn = MagicMock(wraps=real_conn)
        mock_conn.executemany.side_effect = Exception("Simulated batch error")
        # execute() делегируем реальному соединению
        mock_conn.execute.side_effect = real_conn.execute
        mock_conn.commit.side_effect = real_conn.commit
        plugin._conn = mock_conn

        flushed = plugin._flush_buffer()

        # Обе записи должны быть сохранены через fallback
        assert flushed == 2
        assert plugin._total_written == 2
        assert count_rows(real_conn) == 2
        # log_error должен был вызваться
        plugin._ctx.log_error.assert_called_once()

    def test_fallback_counts_errors_on_single_row_failure(self):
        """В fallback: ошибка отдельной строки → total_errors++."""
        plugin = make_plugin()

        plugin._buffer = [
            {"timestamp": 1.0, "frame_id": 1, "camera_id": 0, "event_type": "ok", "data": "{}"},
            {"timestamp": 2.0, "frame_id": 2, "camera_id": 0, "event_type": "bad", "data": "{}"},
        ]

        real_conn = plugin._conn
        mock_conn = MagicMock()
        mock_conn.executemany.side_effect = Exception("batch fail")

        call_count = [0]

        def selective_execute(sql, record):
            call_count[0] += 1
            if call_count[0] == 1:
                # Первая запись — успех
                return real_conn.execute(sql, record)
            else:
                # Вторая запись — ошибка
                raise Exception("row fail")

        mock_conn.execute.side_effect = selective_execute
        mock_conn.commit.side_effect = real_conn.commit
        plugin._conn = mock_conn

        flushed = plugin._flush_buffer()

        assert flushed == 1
        assert plugin._total_errors == 1


# ---------------------------------------------------------------------------
# TestCommands
# ---------------------------------------------------------------------------

class TestCommands:
    def test_cmd_flush(self):
        """Команда flush сбрасывает буфер и возвращает статус."""
        plugin = make_plugin()
        plugin.process([{"frame_id": 5, "timestamp": 1.0}])
        result = plugin._cmd_flush({})

        assert result["status"] == "ok"
        assert result["flushed"] == 1
        assert result["total"] == 1

    def test_cmd_set_batch_size(self):
        """set_batch_size обновляет batch_size в допустимых пределах."""
        plugin = make_plugin()

        result = plugin._cmd_set_batch_size({"batch_size": 500})
        assert result["status"] == "ok"
        assert result["batch_size"] == 500
        assert plugin._reg.batch_size == 500

    def test_cmd_set_batch_size_clamps_min(self):
        """set_batch_size зажимает значение до 1."""
        plugin = make_plugin()
        result = plugin._cmd_set_batch_size({"batch_size": 0})
        assert result["batch_size"] == 1

    def test_cmd_set_batch_size_clamps_max(self):
        """set_batch_size зажимает значение до 10000."""
        plugin = make_plugin()
        result = plugin._cmd_set_batch_size({"batch_size": 99999})
        assert result["batch_size"] == 10000

    def test_cmd_reset_stats(self):
        """reset_stats обнуляет счётчики total_written и total_errors."""
        plugin = make_plugin()
        plugin._total_written = 42
        plugin._total_errors = 7

        result = plugin._cmd_reset_stats({})
        assert result["status"] == "ok"
        assert plugin._total_written == 0
        assert plugin._total_errors == 0

    def test_cmd_get_stats_includes_total_errors(self):
        """get_stats возвращает total_errors."""
        plugin = make_plugin()
        plugin._total_written = 10
        plugin._total_errors = 3

        result = plugin._cmd_get_stats({})
        assert result["status"] == "ok"
        assert result["total_written"] == 10
        assert result["total_errors"] == 3
        assert "pending" in result
        assert "db_path" in result
