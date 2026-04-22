"""Тесты typed commands."""
import pytest

from sql_module.commands import DBQueryCommand, DBExecuteCommand, DBInsertCommand


class TestDBCommands:
    def test_db_query_command(self):
        cmd = DBQueryCommand.model_validate(
            {"command": "db.query", "sql": "SELECT 1", "params": None}
        )
        assert cmd.command == "db.query"
        assert cmd.sql == "SELECT 1"
        assert cmd.timeout == 30

    def test_db_execute_command(self):
        cmd = DBExecuteCommand.model_validate(
            {"command": "db.execute", "sql": "INSERT INTO t VALUES (1)"}
        )
        assert cmd.command == "db.execute"
        assert cmd.sql == "INSERT INTO t VALUES (1)"

    def test_db_insert_command(self):
        cmd = DBInsertCommand.model_validate(
            {"command": "db.insert", "table": "users", "data": {"name": "Alice"}}
        )
        assert cmd.command == "db.insert"
        assert cmd.table == "users"
        assert cmd.data == {"name": "Alice"}

    def test_db_query_command_after_merge_from_message_adapter(self):
        """Формат из MessageAdapter.command: args содержат sql, params. execute_command мержит их."""
        msg = {"command": "db.query", "args": {"sql": "SELECT 1", "params": {}}}
        cmd_flat = {**msg.get("args", {}), "command": msg.get("command")}
        validated = DBQueryCommand.model_validate(cmd_flat)
        assert validated.sql == "SELECT 1"
