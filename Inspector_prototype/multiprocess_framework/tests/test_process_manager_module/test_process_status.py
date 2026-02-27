"""
Тесты для ProcessStatus.

Проверяют мониторинг статуса процессов.
"""

import unittest
from multiprocessing import Process
from multiprocess_framework.modules.Process_manager_module.core import ProcessStatus


def dummy_target():
    """Простая функция-цель для процесса"""
    import time
    time.sleep(0.1)


class TestProcessStatus(unittest.TestCase):
    """Тесты для ProcessStatus"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.processes = []
        # Создаем тестовые процессы
        for i in range(3):
            p = Process(target=dummy_target, name=f"TestProcess{i}")
            self.processes.append(p)
        
        self.status = ProcessStatus(self.processes)
    
    def tearDown(self):
        """Очистка после тестов"""
        for p in self.processes:
            if p.is_alive():
                p.terminate()
                p.join(timeout=1.0)
    
    def test_get_all_status(self):
        """Тест получения статуса всех процессов"""
        status = self.status.get_all_status()
        
        self.assertEqual(len(status), 3)
        for i in range(3):
            self.assertIn(f"TestProcess{i}", status)
    
    def test_get_process_status(self):
        """Тест получения статуса конкретного процесса"""
        status = self.status.get_process_status("TestProcess0")
        
        self.assertIsNotNone(status)
        self.assertIn('alive', status)
        self.assertIn('pid', status)
        self.assertIn('name', status)
    
    def test_get_process_status_not_found(self):
        """Тест получения статуса несуществующего процесса"""
        status = self.status.get_process_status("UnknownProcess")
        self.assertIsNone(status)
    
    def test_get_alive_count(self):
        """Тест подсчета живых процессов"""
        # Процессы еще не запущены
        count = self.status.get_alive_count()
        self.assertEqual(count, 0)
    
    def test_get_dead_count(self):
        """Тест подсчета завершенных процессов"""
        count = self.status.get_dead_count()
        self.assertEqual(count, 3)  # Все процессы еще не запущены
    
    def test_get_total_count(self):
        """Тест получения общего количества процессов"""
        count = self.status.get_total_count()
        self.assertEqual(count, 3)
    
    def test_get_stats(self):
        """Тест получения статистики"""
        stats = self.status.get_stats()
        
        self.assertIn('total', stats)
        self.assertIn('alive', stats)
        self.assertIn('dead', stats)
        self.assertIn('processes', stats)
        
        self.assertEqual(stats['total'], 3)
    
    def test_has_alive_processes(self):
        """Тест проверки наличия живых процессов"""
        # Процессы еще не запущены
        has_alive = self.status.has_alive_processes()
        self.assertFalse(has_alive)
    
    def test_get_process_names(self):
        """Тест получения списка имен процессов"""
        names = self.status.get_process_names()
        
        self.assertEqual(len(names), 3)
        self.assertIn("TestProcess0", names)
        self.assertIn("TestProcess1", names)
        self.assertIn("TestProcess2", names)


if __name__ == '__main__':
    unittest.main()

