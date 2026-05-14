"""
Тесты для CommandAdapter.

Проверяет функциональность адаптера команд.
"""

import unittest
from unittest.mock import Mock

from ..adapters.command_adapter import CommandAdapter
from ..core.command_manager import CommandManager


class TestCommandAdapter(unittest.TestCase):
    """Тесты для CommandAdapter."""

    def setUp(self):
        """Подготовка тестового окружения."""
        self.manager = CommandManager("test_process")
        self.manager.initialize()
        self.adapter = CommandAdapter(self.manager)

    def tearDown(self):
        """Очистка после тестов."""
        if self.manager:
            self.manager.shutdown()

    def test_initialization(self):
        """Тест инициализации адаптера."""
        self.assertEqual(self.adapter.manager, self.manager)
        self.assertEqual(self.adapter.adapter_name, "CommandAdapter")

    def test_setup(self):
        """Тест настройки адаптера."""
        result = self.adapter.setup()

        self.assertTrue(result)
        self.assertTrue(self.adapter._initialized)

    def test_setup_without_manager(self):
        """Тест настройки адаптера без менеджера."""
        adapter = CommandAdapter(None)
        result = adapter.setup()

        self.assertFalse(result)

    def test_get_stats(self):
        """Тест получения статистики адаптера."""
        self.adapter.setup()

        def handler(data):
            return {}

        self.manager.register_command("test", handler)

        stats = self.adapter.get_stats()

        self.assertIsInstance(stats, dict)
        self.assertEqual(stats["adapter_name"], "CommandAdapter")
        self.assertTrue(stats["initialized"])
        self.assertIn("manager_stats", stats)

    def test_execute_via_message_without_process(self):
        """Тест выполнения команды через сообщения без процесса."""
        self.adapter.setup()

        result = self.adapter.execute_via_message("test", {}, ["target"], False)

        self.assertFalse(result)

    def test_execute_via_message_with_process(self):
        """Тест выполнения команды через сообщения с процессом."""
        # Создаем мок процесса
        mock_process = Mock()
        mock_message_manager = Mock()
        mock_message = Mock()
        mock_message.to_dict.return_value = {"command": "test", "data": {}}

        mock_message_manager.create_command_message.return_value = mock_message
        mock_process.message_manager = mock_message_manager

        mock_router = Mock()
        mock_router.send.return_value = {"status": "success"}
        mock_process.router = mock_router

        adapter = CommandAdapter(self.manager, mock_process)
        adapter.setup()

        result = adapter.execute_via_message("test", {"arg": "value"}, ["target"], False)

        self.assertTrue(result)
        mock_message_manager.create_command_message.assert_called_once()
        mock_router.send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
