"""Тесты SQLManager."""
import pytest
from unittest.mock import MagicMock

from sql_module import SQLManager, SQLManagerConfig


class TestSQLManager:
    def test_initialize_shutdown(self, sql_config):
        mgr = SQLManager(config=sql_config)
        assert mgr.initialize()
        assert mgr.is_initialized
        assert mgr.shutdown()
        assert not mgr.is_initialized

    def test_execute_query(self, sql_manager):
        sql_manager.execute("CREATE TABLE t (x INT)")
        sql_manager.execute("INSERT INTO t VALUES (1)")
        sql_manager.execute("INSERT INTO t VALUES (:v)", {"v": 2})
        rows = sql_manager.query("SELECT * FROM t ORDER BY x")
        assert len(rows) == 2
        assert rows[0]["x"] == 1
        assert rows[1]["x"] == 2

    def test_execute_command_query(self, sql_manager):
        sql_manager.execute("CREATE TABLE t (x INT)")
        sql_manager.execute("INSERT INTO t VALUES (1)")
        result = sql_manager.execute_command(
            {"command": "db.query", "sql": "SELECT * FROM t"}
        )
        assert result["status"] == "success"
        assert result["data"] == [{"x": 1}]

    def test_execute_command_execute(self, sql_manager):
        sql_manager.execute("CREATE TABLE t (x INT)")
        result = sql_manager.execute_command(
            {"command": "db.execute", "sql": "INSERT INTO t VALUES (:v)", "params": {"v": 42}}
        )
        assert result["status"] == "success"
        assert result["rows"] == 1

    def test_execute_command_unknown(self, sql_manager):
        result = sql_manager.execute_command({"command": "unknown"})
        assert result["status"] == "error"
        assert "unknown" in result["reason"]

    def test_normalize_command_direct(self, sql_manager):
        """Прямой формат: sql, params на верхнем уровне."""
        cmd = {"command": "db.query", "sql": "SELECT 1", "params": {}}
        flat = sql_manager._normalize_command(cmd)
        assert flat["command"] == "db.query"
        assert flat["sql"] == "SELECT 1"

    def test_normalize_command_message_adapter(self, sql_manager):
        """MessageAdapter: sql, params в args."""
        cmd = {"command": "db.query", "args": {"sql": "SELECT * FROM t", "params": {"id": 1}}}
        flat = sql_manager._normalize_command(cmd)
        assert flat["command"] == "db.query"
        assert flat["sql"] == "SELECT * FROM t"
        assert flat["params"] == {"id": 1}

    def test_uow_connection(self, sql_manager):
        uow = sql_manager.uow()
        with uow.connection() as conn:
            from sqlalchemy import text
            conn.execute(text("CREATE TABLE uow_test (id INT)"))
            conn.execute(text("INSERT INTO uow_test VALUES (1)"))

    @pytest.mark.asyncio
    async def test_uow_async_connection(self, sql_manager):
        """Async UoW: создание таблицы, вставка и проверка в одной транзакции."""
        uow = sql_manager.uow_async()
        async with uow.connection() as conn:
            from sqlalchemy import text
            await conn.execute(text("CREATE TABLE uow_async_test (id INT)"))
            await conn.execute(text("INSERT INTO uow_async_test VALUES (1)"))
            result = await conn.execute(text("SELECT * FROM uow_async_test"))
            rows = [dict(zip(result.keys(), r)) for r in result.fetchall()]
        assert rows == [{"id": 1}]

    @pytest.mark.asyncio
    async def test_uow_async_lazy_adapter(self, sql_config):
        """Async адаптер создаётся только при первом вызове uow_async."""
        mgr = SQLManager(config=sql_config)
        mgr.initialize()
        assert mgr._async_adapter is None
        uow = mgr.uow_async()
        assert mgr._async_adapter is not None
        async with uow.connection() as conn:
            from sqlalchemy import text
            await conn.execute(text("SELECT 1"))
        mgr.shutdown()
        assert mgr._async_adapter is None

    def test_record_timing_on_query(self, sql_config):
        """При наличии stats_manager вызывается _record_timing."""
        mock_stats = MagicMock()
        mgr = SQLManager(config=sql_config, managers={"stats": mock_stats})
        mgr.initialize()
        mgr.execute("CREATE TABLE t (x INT)")
        mgr.execute("INSERT INTO t VALUES (1)")
        mgr.query("SELECT * FROM t")
        mgr.shutdown()
        assert mock_stats.record_timing.called
        calls = [c for c in mock_stats.record_timing.call_args_list if "db.query.duration" in str(c)]
        assert len(calls) >= 1

    def test_track_error_on_execute_command_failure(self, sql_config):
        """При исключении в execute_command вызывается _track_error."""
        mock_errors = MagicMock()
        mgr = SQLManager(config=sql_config, managers={"errors": mock_errors})
        mgr.initialize()
        result = mgr.execute_command({"command": "db.query", "sql": "SELECT * FROM nonexistent"})
        mgr.shutdown()
        assert result["status"] == "error"
        assert mock_errors.track_error.called
