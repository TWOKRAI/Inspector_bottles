"""
Тесты для ProcessPriority.

Проверяют управление приоритетами процессов.
"""

import unittest
import time
from multiprocessing import Process
from multiprocess_framework.modules.Process_manager_module.core import ProcessPriority
from multiprocess_framework.modules.Logger_module import LoggerManager


def dummy_target():
    """Простая функция-цель для процесса"""
    import time
    time.sleep(1)


class TestProcessPriority(unittest.TestCase):
    """Тесты для ProcessPriority"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.priority = ProcessPriority()
        # Также создаем версию с logger для тестирования
        self.logger = LoggerManager()
        self.logger.initialize()
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
    
    def test_is_valid_priority(self):
        """Тест проверки валидности приоритета"""
        self.assertTrue(ProcessPriority.is_valid_priority("high"))
        self.assertTrue(ProcessPriority.is_valid_priority("normal"))
        self.assertTrue(ProcessPriority.is_valid_priority("low"))
        self.assertFalse(ProcessPriority.is_valid_priority("invalid"))
    
    def test_priority_map(self):
        """Тест наличия всех приоритетов в маппинге"""
        valid_priorities = ['high', 'normal', 'low', 'below_normal', 'above_normal']
        
        for priority in valid_priorities:
            self.assertIn(priority, ProcessPriority.PRIORITY_MAP)
            self.assertIsNotNone(ProcessPriority.PRIORITY_MAP[priority])
    
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
        
        # Запускаем процесс
        process.start()
        time.sleep(0.1)
        
        # Применяем приоритет
        result = self.priority_with_logger.apply_priority(process, delay=0.1)
        
        # Проверяем что метод выполнился (может вернуть False из-за прав доступа)
        self.assertIsInstance(result, bool)
        
        # Останавливаем процесс
        process.terminate()
        process.join(timeout=1.0)


if __name__ == '__main__':
    unittest.main()

