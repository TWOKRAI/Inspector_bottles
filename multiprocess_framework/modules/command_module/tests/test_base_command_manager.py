"""
Тесты для BaseCommandManager.

Проверяет лёгкий командный менеджер без ObservableMixin.
"""

import unittest

from ..core.base_command_manager import BaseCommandManager


class TestBaseCommandManager(unittest.TestCase):
    """Тесты для BaseCommandManager."""

    def setUp(self):
        self.manager = BaseCommandManager("test_process")

    def test_initialization(self):
        self.assertEqual(self.manager.process_name, "test_process")

    def test_register_command(self):
        def handler(data):
            return {"result": "ok"}

        result = self.manager.register_command("test", handler)
        self.assertTrue(result)
        commands = self.manager.get_commands()
        self.assertEqual(len(commands), 1)

    def test_register_duplicate_rejected(self):
        def h(data):
            return {}

        self.assertTrue(self.manager.register_command("dup", h))
        self.assertFalse(self.manager.register_command("dup", h))

    def test_overwrite_command(self):
        def v1(data):
            return {"v": 1}

        def v2(data):
            return {"v": 2}

        self.manager.register_command("cmd", v1)
        self.manager.overwrite_command("cmd", v2)

        result = self.manager.handle_command({"command": "cmd", "data": {}})
        self.assertEqual(result["v"], 2)

    def test_handle_command(self):
        def handler(data):
            return {"result": data.get("value", 0) * 2}

        self.manager.register_command("process", handler)
        result = self.manager.handle_command({"command": "process", "data": {"value": 5}})
        self.assertEqual(result["result"], 10)

    def test_handle_command_not_found(self):
        result = self.manager.handle_command({"command": "unknown", "data": {}})
        self.assertEqual(result["status"], "error")

    def test_handle_command_exception_returns_error(self):
        def bad(data):
            raise RuntimeError("boom")

        self.manager.register_command("bad", bad)
        result = self.manager.handle_command({"command": "bad", "data": {}})
        self.assertEqual(result["status"], "error")
        self.assertIn("boom", result["reason"])

    def test_get_commands(self):
        def h1(data):
            return {}

        def h2(data):
            return {}

        self.manager.register_command("cmd1", h1)
        self.manager.register_command("cmd2", h2)

        commands = self.manager.get_commands()
        self.assertEqual(len(commands), 2)
        keys = [c["key"] for c in commands]
        self.assertIn("cmd1", keys)
        self.assertIn("cmd2", keys)

    def test_get_command_info(self):
        def h(data):
            return {}

        self.manager.register_command("info_test", h)
        info = self.manager.get_command_info("info_test")
        self.assertIsNotNone(info)
        self.assertEqual(info["key"], "info_test")

    def test_get_command_info_not_found(self):
        self.assertIsNone(self.manager.get_command_info("missing"))


if __name__ == "__main__":
    unittest.main()
