"""
Тесты для ProcessPriority (refactored).

Проверяют управление приоритетами процессов.
"""

import unittest
import time
from multiprocessing import Process
from multiprocess_framework.refactored.modules.process_manager_module.core import (
    ProcessPriority,
)


def _mock_logger():
    return type("MockLogger", (), {"_log_info": lambda *a, **k: None, "_log_warning": lambda *a, **k: None})()


def dummy_target():
    """Простая функция-цель для процесса"""
    time.sleep(1)


class TestProcessPriority(unittest.TestCase):
    """Тесты для ProcessPriority"""

    def setUp(self):
        """Подготовка тестового окружения"""
        self.priority = ProcessPriority()
        self.logger = _mock_logger()
        self.priority_with_logger = ProcessPriority(self.logger)

    def test_register_priority(self):
        """Тест регистрации приоритета"""
        self.priority.register_priority("TestProcess", "high")

        priority = self.priority.get_priority("TestProcess")
        self.assertEqual(priority, "high")

    def test_get_priority_default(self):
        """Тест получения приоритета с дефолтным значением"""
        priority = self.priority.get_priority("UnknownProcess", default="normal")
        self.assertEqual(priority, "normal")

    def test_priority_with_logger(self):
        """Тест ProcessPriority с LoggerManager"""
        self.priority_with_logger.register_priority("TestProcess", "high")

        priority = self.priority_with_logger.get_priority("TestProcess")
        self.assertEqual(priority, "high")

    def test_priority_without_logger(self):
        """Тест ProcessPriority без LoggerManager (должен работать)"""
        self.priority.register_priority("TestProcess", "high")

        priority = self.priority.get_priority("TestProcess")
        self.assertEqual(priority, "high")

    def test_apply_priority(self):
        """Тест применения приоритета к процессу"""
        process = Process(target=dummy_target, name="TestProcess")
        self.priority_with_logger.register_priority("TestProcess", "normal")

        process.start()
        time.sleep(0.1)

        result = self.priority_with_logger.apply_priority(process, delay=0.1)

        self.assertIsInstance(result, bool)

        process.terminate()
        process.join(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
