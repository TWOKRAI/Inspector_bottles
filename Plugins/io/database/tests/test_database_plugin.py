"""Тесты DatabasePlugin (SQLManager-реализация).

Используем in-memory SQLManager (StaticPool — данные живут в одном соединении)
и mock PluginContext — без worker_manager. Raw sqlite3 больше не используется.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from Plugins.io.database.plugin import DatabasePlugin
from Plugins.io.database.schemas import DetectionSchema

from Services.sql import SQLManager, SQLManagerConfig


# ---------------------------------------------------------------------------
# Вспомогательные фикстуры
# ---------------------------------------------------------------------------


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


def make_sql() -> SQLManager:
    """Создать инициализированный in-memory SQLManager с таблицей detections.

    fork_safe НЕ задаём: для `:memory:` фабрика выбирает StaticPool (одно
    соединение), иначе NullPool пересоздавал бы БД на каждом запросе.
    """
    sql = SQLManager(
        config=SQLManagerConfig(url="sqlite:///:memory:", dialect="sqlite"),
        managers={},
        process=None,
    )
    sql.initialize()
    sql.create_tables([DetectionSchema])
    return sql


def make_plugin(config: dict | None = None) -> DatabasePlugin:
    """Создать сконфигурированный плагин с in-memory SQLManager."""
    plugin = DatabasePlugin()
    ctx = make_ctx(config)
    plugin.configure(ctx)
    # Внедряем настоящий SQLManager после configure, до start (start делает fork-конфиг).
    plugin._sql = make_sql()
    return plugin


def count_rows(plugin: DatabasePlugin) -> int:
    """Подсчитать записи в таблице detections через SQLManager."""
    return plugin._sql.query("SELECT COUNT(*) AS c FROM detections")[0]["c"]


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
        # SQLManager НЕ создаётся в configure (fork-safety) — только в start().
        assert plugin._sql is None

    def test_configure_custom(self):
        """Пользовательские параметры принимаются."""
        plugin = DatabasePlugin()
        ctx = make_ctx({"batch_size": 50, "flush_interval_sec": 5.0, "db_path": "/tmp/test.db"})
        plugin.configure(ctx)

        assert plugin._reg.batch_size == 50
        assert plugin._reg.flush_interval_sec == 5.0
        assert plugin._reg.db_path == "/tmp/test.db"


# ---------------------------------------------------------------------------
# TestSchema / DDL
# ---------------------------------------------------------------------------


class TestSchema:
    def test_create_tables_builds_detections(self):
        """create_tables([DetectionSchema]) создаёт таблицу detections (auto-DDL)."""
        sql = make_sql()
        # Если таблицы нет — запрос упадёт; считаем успехом наличие 0 строк.
        rows = sql.query("SELECT COUNT(*) AS c FROM detections")
        assert rows[0]["c"] == 0
        sql.shutdown()


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
        assert count_rows(plugin) == 3


# ---------------------------------------------------------------------------
# TestFlush
# ---------------------------------------------------------------------------


class TestFlush:
    def test_flush_writes_to_db(self):
        """_flush_buffer() пишет записи в БД через SQLManager."""
        plugin = make_plugin()
        plugin.process(
            [
                {"frame_id": 10, "timestamp": 1.0},
                {"frame_id": 11, "timestamp": 2.0},
            ]
        )
        flushed = plugin._flush_buffer()

        assert flushed == 2
        assert count_rows(plugin) == 2
        assert plugin._total_written == 2

    def test_flush_empty_buffer(self):
        """Flush пустого буфера возвращает 0."""
        plugin = make_plugin()
        result = plugin._flush_buffer()

        assert result == 0
        assert count_rows(plugin) == 0

    def test_created_at_is_set_in_code(self):
        """created_at проставляется в коде (не SQL-default)."""
        plugin = make_plugin()
        before = time.time()
        plugin.process([{"frame_id": 1, "timestamp": 1.0}])
        plugin._flush_buffer()
        after = time.time()

        row = plugin._sql.query("SELECT created_at FROM detections")[0]
        assert row["created_at"] is not None
        assert before <= row["created_at"] <= after

    def test_fallback_on_batch_error(self):
        """При ошибке batch insert_many — fallback по одной записи."""
        plugin = make_plugin()
        plugin._buffer = [
            {"timestamp": 1.0, "frame_id": 1, "camera_id": 0, "event_type": "test", "data": "{}"},
            {"timestamp": 2.0, "frame_id": 2, "camera_id": 0, "event_type": "test", "data": "{}"},
        ]

        # get_repository кэширует инстанс — патчим именно его insert_many.
        repo = plugin._sql.get_repository(DetectionSchema)
        real_insert_many = repo.insert_many

        def insert_side_effect(rows):
            if len(rows) > 1:
                raise Exception("Simulated batch error")
            return real_insert_many(rows)

        with patch.object(repo, "insert_many", side_effect=insert_side_effect):
            flushed = plugin._flush_buffer()

        # Обе записи сохранены через fallback one-by-one.
        assert flushed == 2
        assert plugin._total_written == 2
        assert count_rows(plugin) == 2
        plugin._ctx.log_error.assert_called_once()

    def test_fallback_counts_errors_on_single_row_failure(self):
        """В fallback: ошибка отдельной строки → total_errors++."""
        plugin = make_plugin()
        plugin._buffer = [
            {"timestamp": 1.0, "frame_id": 1, "camera_id": 0, "event_type": "ok", "data": "{}"},
            {"timestamp": 2.0, "frame_id": 2, "camera_id": 0, "event_type": "bad", "data": "{}"},
        ]

        repo = plugin._sql.get_repository(DetectionSchema)
        real_insert_many = repo.insert_many

        def insert_side_effect(rows):
            if len(rows) > 1:
                raise Exception("batch fail")
            # frame_id==1 → успех, остальное → ошибка строки.
            if rows[0].frame_id == 1:
                return real_insert_many(rows)
            raise Exception("row fail")

        with patch.object(repo, "insert_many", side_effect=insert_side_effect):
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
