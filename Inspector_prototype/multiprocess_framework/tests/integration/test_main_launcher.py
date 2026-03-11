"""
Тесты для SystemLauncher (refactored).

Проверяют работу главного запускателя системы.
"""

import unittest
from multiprocess_framework.refactored.modules.process_manager_module import (
    SystemLauncher,
    ProcessSpawner,
)


class TestSystemLauncher(unittest.TestCase):
    """Тесты для SystemLauncher"""

    def setUp(self):
        """Подготовка тестового окружения"""
        self.launcher = SystemLauncher()

    def test_launcher_initialization(self):
        """Тест инициализации запускателя"""
        self.assertIsNone(self.launcher._spawner)
        self.assertEqual(self.launcher._processes, [])

    def test_launcher_add_process(self):
        """Тест добавления процесса"""
        self.launcher.add_process("proc1", {"name": "proc1"})

        self.assertEqual(len(self.launcher._processes), 1)
        self.assertEqual(self.launcher._processes[0][0], "proc1")

    def test_get_status(self):
        """Тест получения статуса системы"""
        status = self.launcher.get_status()

        self.assertIsInstance(status, dict)
        self.assertIn("spawner_running", status)
        self.assertFalse(status["spawner_running"])

    def test_get_stats(self):
        """Тест получения статистики системы"""
        stats = self.launcher.get_stats()

        self.assertIsInstance(stats, dict)
        self.assertIn("spawner", stats)
        self.assertFalse(stats["spawner"]["is_running"])
