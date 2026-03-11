"""
Тесты для ProcessRegistry (замена ProcessLifecycle).

Проверяют управление жизненным циклом процессов через ProcessRegistry.
"""

import unittest
import time
from multiprocessing import Process, Event
from multiprocess_framework.refactored.modules.process_manager_module.core import (
    ProcessRegistry,
)


def _mock_logger():
    return type("MockLogger", (), {"_log_info": lambda *a, **k: None, "_log_warning": lambda *a, **k: None, "_log_error": lambda *a, **k: None})()


def dummy_target():
    """Простая функция-цель для процесса"""
    time.sleep(1)


class TestProcessRegistry(unittest.TestCase):
    """Тесты для ProcessRegistry (lifecycle)"""

    def setUp(self):
        """Подготовка тестового окружения"""
        self.stop_event = Event()
        self.registry = ProcessRegistry(self.stop_event)
        self.logger = _mock_logger()
        self.registry_with_logger = ProcessRegistry(self.stop_event, self.logger)

    def tearDown(self):
        """Очистка после тестов"""
        for reg in [self.registry, self.registry_with_logger]:
            reg.stop_all(timeout=1.0)

    def test_add_process(self):
        """Тест добавления процесса"""
        process = Process(target=dummy_target, name="TestProcess")
        self.registry.add_process(process)

        self.assertIn(process, self.registry.os_processes)

    def test_start_all(self):
        """Тест запуска всех процессов"""
        process = Process(target=dummy_target, name="TestProcess")
        self.registry.add_process(process)

        self.registry.start_all()

        time.sleep(0.1)

        self.assertTrue(process.is_alive())

        process.terminate()
        process.join(timeout=1.0)

    def test_get_process_by_name(self):
        """Тест получения процесса по имени"""
        process = Process(target=dummy_target, name="TestProcess")
        self.registry.add_process(process)

        found = self.registry.get_process_by_name("TestProcess")
        self.assertIs(found, process)

    def test_stop_all(self):
        """Тест остановки всех процессов"""
        process = Process(target=dummy_target, name="TestProcess")
        self.registry.add_process(process)

        process.start()
        time.sleep(0.1)

        self.registry.stop_all(timeout=1.0)

        self.assertFalse(process.is_alive())

    def test_registry_with_logger(self):
        """Тест ProcessRegistry с LoggerManager"""
        process = Process(target=dummy_target, name="TestProcess")
        self.registry_with_logger.add_process(process)

        self.assertIn(process, self.registry_with_logger.os_processes)

        self.registry_with_logger.start_all()
        time.sleep(0.1)

        self.assertTrue(process.is_alive())

        self.registry_with_logger.stop_all(timeout=1.0)
        self.assertFalse(process.is_alive())

    def test_registry_without_logger(self):
        """Тест ProcessRegistry без LoggerManager (должен работать)"""
        process = Process(target=dummy_target, name="TestProcess")
        self.registry.add_process(process)

        self.registry.start_all()
        time.sleep(0.1)

        self.assertTrue(process.is_alive())

        self.registry.stop_all(timeout=1.0)
        self.assertFalse(process.is_alive())


if __name__ == "__main__":
    unittest.main()
