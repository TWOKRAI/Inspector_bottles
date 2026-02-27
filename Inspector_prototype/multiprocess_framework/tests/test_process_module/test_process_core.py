"""
Тесты для ProcessCore.

Проверяют базовую функциональность жизненного цикла процесса.
"""

import unittest
from multiprocessing import Queue
from multiprocess_framework.modules.Process_module.core import ProcessCore
from multiprocess_framework.modules.Process_manager_module.ProcessInteractionManager import ProcessInteractionManager


class TestProcessCore(unittest.TestCase):
    """Тесты для ProcessCore"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.process_name = "TestCore"
        self.interaction_manager = ProcessInteractionManager()
        self.config = {}
    
    def test_core_initialization(self):
        """Тест инициализации ядра процесса"""
        core = ProcessCore(
            name=self.process_name,
            interaction_manager=self.interaction_manager,
            config=self.config
        )
        
        # Проверяем базовые атрибуты
        self.assertEqual(core.name, self.process_name)
        self.assertEqual(core.config, self.config)
        self.assertFalse(core.stop_process)
        
        # Проверяем наличие очередей
        self.assertIn("system", core.queues)
        self.assertIn("data", core.queues)
        self.assertIn("broadcast", core.queues)
        self.assertIn("custom", core.queues)
    
    def test_lifecycle(self):
        """Тест жизненного цикла"""
        core = ProcessCore(
            name=self.process_name,
            interaction_manager=self.interaction_manager,
            config=self.config
        )
        
        # Проверяем начальное состояние
        self.assertFalse(core.should_stop())
        
        # Запускаем процесс
        core.run()
        self.assertFalse(core.should_stop())
        
        # Останавливаем процесс
        core.stop()
        self.assertTrue(core.should_stop())
    
    def test_queue_registration(self):
        """Тест регистрации дополнительных очередей"""
        core = ProcessCore(
            name=self.process_name,
            interaction_manager=self.interaction_manager,
            config=self.config
        )
        
        custom_queue = Queue(maxsize=10)
        core.register_queue("custom_test", custom_queue)
        
        self.assertIn("custom_test", core.queues)
        self.assertEqual(core.queues["custom_test"], custom_queue)
    
    def test_config_manager_integration(self):
        """Тест интеграции с config_manager"""
        from multiprocess_framework.modules.Base_manager_module.config_manager import ConfigManager
        
        config_manager = ConfigManager({
            'test_key': 'test_value'
        })
        
        core = ProcessCore(
            name=self.process_name,
            interaction_manager=self.interaction_manager,
            config=self.config,
            config_manager=config_manager
        )
        
        self.assertEqual(core.config_manager, config_manager)


if __name__ == '__main__':
    unittest.main()

