"""
Тесты для CommandManager.

Проверяет основную функциональность командного менеджера:
- Инициализация и завершение работы
- Регистрация команд
- Выполнение команд
- Работа с метаданными и тегами
- Интеграция с ObservableMixin
"""

import unittest

from ..core.command_manager import CommandManager
from ...dispatch_module import DispatchStrategy


class TestCommandManager(unittest.TestCase):
    """Тесты для CommandManager."""

    def setUp(self):
        """Подготовка тестового окружения."""
        self.manager = CommandManager("test_process")
        self.manager.initialize()

    def tearDown(self):
        """Очистка после тестов."""
        if self.manager:
            self.manager.shutdown()

    def test_initialization(self):
        """Тест инициализации менеджера."""
        self.assertTrue(self.manager.is_initialized)
        self.assertEqual(self.manager.manager_name, "test_process")
        self.assertEqual(self.manager.process_name, "test_process")  # Для обратной совместимости
        self.assertIsNotNone(self.manager.dispatcher)

    def test_lifecycle_initialize(self):
        """Тест метода initialize()."""
        manager = CommandManager("lifecycle_test")
        self.assertFalse(manager.is_initialized)
        result = manager.initialize()
        self.assertTrue(result)
        self.assertTrue(manager.is_initialized)
        manager.shutdown()

    def test_lifecycle_shutdown(self):
        """Тест метода shutdown()."""
        manager = CommandManager("lifecycle_test")
        manager.initialize()
        self.assertTrue(manager.is_initialized)
        result = manager.shutdown()
        self.assertTrue(result)
        self.assertFalse(manager.is_initialized)

    def test_register_command(self):
        """Тест регистрации команды."""

        def test_handler(data):
            return {"result": data.get("value", 0) * 2}

        result = self.manager.register_command("test", test_handler)

        self.assertTrue(result)
        commands = self.manager.get_commands()
        self.assertGreater(len(commands), 0)

    def test_register_command_with_metadata(self):
        """Тест регистрации команды с метаданными."""

        def test_handler(data):
            return {"result": "ok"}

        result = self.manager.register_command(
            "test", test_handler, metadata={"description": "Test command", "version": "1.0"}, tags=["test", "example"]
        )

        self.assertTrue(result)
        info = self.manager.get_command_info("test")
        self.assertIsNotNone(info)
        self.assertEqual(info["metadata"]["description"], "Test command")

    def test_handle_command(self):
        """Тест выполнения команды."""

        def process_handler(data):
            return {"result": data.get("value", 0) * 2}

        self.manager.register_command("process", process_handler)

        message = {"command": "process", "data": {"value": 5}}
        result = self.manager.handle_command(message)

        self.assertEqual(result["result"], 10)

    def test_handle_command_not_found(self):
        """Тест выполнения несуществующей команды."""
        message = {"command": "unknown", "data": {}}
        result = self.manager.handle_command(message)

        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("status"), "error")

    def test_get_commands(self):
        """Тест получения списка команд."""

        def handler1(data):
            return {}

        def handler2(data):
            return {}

        self.manager.register_command("cmd1", handler1)
        self.manager.register_command("cmd2", handler2)

        commands = self.manager.get_commands()
        self.assertGreaterEqual(len(commands), 2)
        command_keys = [cmd.get("key", "") for cmd in commands]
        self.assertIn("cmd1", command_keys)
        self.assertIn("cmd2", command_keys)

    def test_get_command_info(self):
        """Тест получения информации о команде."""

        def test_handler(data):
            return {}

        self.manager.register_command("test", test_handler, metadata={"description": "Test"})

        info = self.manager.get_command_info("test")
        self.assertIsNotNone(info)
        self.assertEqual(info["key"], "test")

    def test_get_commands_by_tag(self):
        """Тест получения команд по тегу."""

        def vision_handler(data):
            return {}

        def audio_handler(data):
            return {}

        self.manager.register_command("vision_process", vision_handler, tags=["vision", "image"])

        self.manager.register_command("audio_process", audio_handler, tags=["audio", "sound"])

        vision_commands = self.manager.get_commands_by_tag("vision")
        self.assertEqual(len(vision_commands), 1)
        self.assertEqual(vision_commands[0]["key"], "vision_process")

    def test_update_command_metadata(self):
        """Тест обновления метаданных команды."""

        def test_handler(data):
            return {}

        self.manager.register_command("test", test_handler, metadata={"version": "1.0"})

        result = self.manager.update_command_metadata("test", {"version": "2.0", "updated": True})

        self.assertTrue(result)
        info = self.manager.get_command_info("test")
        self.assertEqual(info["metadata"]["version"], "2.0")
        self.assertTrue(info["metadata"]["updated"])

    def test_update_command_tags(self):
        """Тест обновления тегов команды."""

        def test_handler(data):
            return {}

        self.manager.register_command("test", test_handler, tags=["old"])

        result = self.manager.update_command_tags("test", ["new", "updated"])

        self.assertTrue(result)
        info = self.manager.get_command_info("test")
        self.assertIn("new", info["tags"])
        self.assertIn("updated", info["tags"])

    def test_overwrite_command(self):
        """Тест перезаписи команды."""

        def old_handler(data):
            return {"result": "old"}

        def new_handler(data):
            return {"result": "new"}

        self.manager.register_command("test", old_handler)

        result = self.manager.overwrite_command("test", new_handler)

        self.assertTrue(result)
        message = {"command": "test", "data": {}}
        result = self.manager.handle_command(message)
        self.assertEqual(result["result"], "new")

    def test_get_stats(self):
        """Тест получения статистики."""

        def handler1(data):
            return {}

        def handler2(data):
            return {}

        self.manager.register_command("cmd1", handler1)
        self.manager.register_command("cmd2", handler2)

        stats = self.manager.get_stats()

        self.assertIsInstance(stats, dict)
        self.assertEqual(stats["total_commands"], 2)
        self.assertIn("cmd1", stats["commands"])
        self.assertIn("cmd2", stats["commands"])
        self.assertEqual(stats["process_name"], "test_process")

    def test_handle_command_expects_full_message(self):
        """handle_command с expects_full_message=True передаёт всё сообщение в handler."""
        received = {}

        def full_handler(message):
            received["command"] = message.get("command")
            received["extra"] = message.get("extra")
            return {"ok": True}

        self.manager.register_command("full", full_handler, expects_full_message=True)

        message = {"command": "full", "data": {"v": 1}, "extra": "metadata"}
        result = self.manager.handle_command(message)

        self.assertEqual(result["ok"], True)
        self.assertEqual(received["command"], "full")
        self.assertEqual(received["extra"], "metadata")

    def test_handle_command_handler_exception_returns_error(self):
        """Исключение внутри обработчика перехватывается Dispatcher и возвращается как {"status": "error"}."""

        def broken_handler(data):
            raise ValueError("Something went wrong")

        self.manager.register_command("broken", broken_handler)

        result = self.manager.handle_command({"command": "broken", "data": {}})
        self.assertEqual(result["status"], "error")
        self.assertIn("Something went wrong", result["reason"])

    def test_register_duplicate_command_rejected(self):
        """Повторная регистрация той же команды отклоняется."""

        def h1(data):
            return {"v": 1}

        def h2(data):
            return {"v": 2}

        self.assertTrue(self.manager.register_command("dup", h1))
        self.assertFalse(self.manager.register_command("dup", h2))

        result = self.manager.handle_command({"command": "dup", "data": {}})
        self.assertEqual(result["v"], 1)

    def test_handle_command_with_fallback_strategy(self):
        """register_command с FALLBACK_MATCH и явной стратегией в сообщении."""

        def fast(data):
            return {"speed": "fast"}

        def slow(data):
            return {"speed": "slow"}

        self.manager.register_command("proc", slow, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=1)
        self.manager.register_command("proc", fast, strategy=DispatchStrategy.FALLBACK_MATCH, efficiency=10)

        result = self.manager.handle_command({"command": "proc", "strategy": "fallback", "data": {}})
        self.assertEqual(result["speed"], "fast")


if __name__ == "__main__":
    unittest.main()
