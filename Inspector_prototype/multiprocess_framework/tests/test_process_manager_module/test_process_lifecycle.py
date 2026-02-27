"""
Тесты для ProcessLifecycle.

Проверяют управление жизненным циклом процессов.
"""

import unittest
import time
from multiprocessing import Process, Event
from multiprocess_framework.modules.Process_manager_module.core import ProcessLifecycle
from multiprocess_framework.modules.Logger_module import LoggerManager


def dummy_target():
    """Простая функция-цель для процесса"""
    import time
    time.sleep(1)


class TestProcessLifecycle(unittest.TestCase):
    """Тесты для ProcessLifecycle"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.stop_event = Event()
        self.lifecycle = ProcessLifecycle(self.stop_event)
        # Также создаем версию с logger для тестирования
        self.logger = LoggerManager()
        self.logger.initialize()
        self.lifecycle_with_logger = ProcessLifecycle(self.stop_event, self.logger)
    
    def tearDown(self):
        """Очистка после тестов"""
        # Останавливаем все процессы
        for lifecycle in [self.lifecycle, self.lifecycle_with_logger]:
            for p in lifecycle.os_processes:
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=1.0)
    
    def test_add_process(self):
        """Тест добавления процесса"""
        process = Process(target=dummy_target, name="TestProcess")
        self.lifecycle.add_process(process)
        
        self.assertIn(process, self.lifecycle.os_processes)
    
    def test_start_all(self):
        """Тест запуска всех процессов"""
        process = Process(target=dummy_target, name="TestProcess")
        self.lifecycle.add_process(process)
        
        self.lifecycle.start_all()
        
        # Даем процессу время на запуск
        time.sleep(0.1)
        
        self.assertTrue(process.is_alive())
        
        # Останавливаем
        process.terminate()
        process.join(timeout=1.0)
    
    def test_get_alive_processes(self):
        """Тест получения живых процессов"""
        process = Process(target=dummy_target, name="TestProcess")
        self.lifecycle.add_process(process)
        
        # Процесс еще не запущен
        alive = self.lifecycle.get_alive_processes()
        self.assertEqual(len(alive), 0)
        
        # Запускаем
        process.start()
        time.sleep(0.1)
        
        alive = self.lifecycle.get_alive_processes()
        self.assertEqual(len(alive), 1)
        
        # Останавливаем
        process.terminate()
        process.join(timeout=1.0)
    
    def test_get_dead_processes(self):
        """Тест получения завершенных процессов"""
        process = Process(target=dummy_target, name="TestProcess")
        self.lifecycle.add_process(process)
        
        # Процесс еще не запущен (считается завершенным)
        dead = self.lifecycle.get_dead_processes()
        self.assertEqual(len(dead), 1)
    
    def test_stop_all(self):
        """Тест остановки всех процессов"""
        process = Process(target=dummy_target, name="TestProcess")
        self.lifecycle.add_process(process)
        
        # Запускаем
        process.start()
        time.sleep(0.1)
        
        # Останавливаем
        self.lifecycle.stop_all(timeout=1.0)
        
        # Процесс должен быть завершен
        self.assertFalse(process.is_alive())
    
    def test_lifecycle_with_logger(self):
        """Тест ProcessLifecycle с LoggerManager"""
        process = Process(target=dummy_target, name="TestProcess")
        self.lifecycle_with_logger.add_process(process)
        
        self.assertIn(process, self.lifecycle_with_logger.os_processes)
        
        # Запускаем
        self.lifecycle_with_logger.start_all()
        time.sleep(0.1)
        
        self.assertTrue(process.is_alive())
        
        # Останавливаем
        self.lifecycle_with_logger.stop_all(timeout=1.0)
        self.assertFalse(process.is_alive())
    
    def test_lifecycle_without_logger(self):
        """Тест ProcessLifecycle без LoggerManager (должен работать)"""
        process = Process(target=dummy_target, name="TestProcess")
        self.lifecycle.add_process(process)
        
        # Должен работать без logger
        self.lifecycle.start_all()
        time.sleep(0.1)
        
        self.assertTrue(process.is_alive())
        
        self.lifecycle.stop_all(timeout=1.0)
        self.assertFalse(process.is_alive())


if __name__ == '__main__':
    unittest.main()

