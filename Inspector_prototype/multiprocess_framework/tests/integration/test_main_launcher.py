"""
Тесты для SystemLauncher.

Проверяют работу главного запускателя системы.
"""

import unittest
from multiprocess_framework.modules.Process_manager_module import SystemLauncher
from multiprocess_framework.modules.Process_manager_module import ProcessManagerBootstrap


class TestSystemLauncher(unittest.TestCase):
    """Тесты для SystemLauncher"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.launcher = SystemLauncher()
    
    def test_launcher_initialization(self):
        """Тест инициализации запускателя"""
        self.assertIsNotNone(self.launcher.bootstrap)
        self.assertIsInstance(self.launcher.bootstrap, ProcessManagerBootstrap)
    
    def test_launcher_with_custom_bootstrap(self):
        """Тест инициализации с кастомным bootstrap"""
        bootstrap = ProcessManagerBootstrap()
        launcher = SystemLauncher(bootstrap=bootstrap)
        
        self.assertEqual(launcher.bootstrap, bootstrap)
    
    def test_get_status(self):
        """Тест получения статуса системы"""
        status = self.launcher.get_status()
        
        self.assertIsInstance(status, dict)
        self.assertIn('bootstrap_running', status)
    
    def test_get_stats(self):
        """Тест получения статистики системы"""
        stats = self.launcher.get_stats()
        
        self.assertIsInstance(stats, dict)
        self.assertIn('bootstrap', stats)


if __name__ == '__main__':
    unittest.main()

