"""Тесты typed commands."""

from Services.sql.commands import DBQueryCommand, DBExecuteCommand, DBInsertCommand


class TestDBCommands:
    def test_db_query_command(self):
        cmd = DBQueryCommand.model_validate({"command": "db.query", "sql": "SELECT 1", "params": None})
        assert cmd.command == "db.query"
        assert cmd.sql == "SELECT 1"
        assert cmd.timeout == 30

    def test_db_execute_command(self):
        cmd = DBExecuteCommand.model_validate({"command": "db.execute", "sql": "INSERT INTO t VALUES (1)"})
        assert cmd.command == "db.execute"
        assert cmd.sql == "INSERT INTO t VALUES (1)"

    def test_db_insert_command(self):
        cmd = DBInsertCommand.model_validate({"command": "db.insert", "table": "users", "data": {"name": "Alice"}})
        assert cmd.command == "db.insert"
        assert cmd.table == "users"
        assert cmd.data == {"name": "Alice"}

    def test_db_query_command_from_unified_envelope(self):
        """Единый конверт (Ф7 G.2): payload под data. execute_command разворачивает его."""
        msg = {"command": "db.query", "data": {"sql": "SELECT 1", "params": {}}}
        cmd_flat = {"command": msg.get("command"), **msg.get("data", {})}
        validated = DBQueryCommand.model_validate(cmd_flat)
        assert validated.sql == "SELECT 1"
