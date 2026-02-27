"""
Тесты для ProcessModule (обновлены под новую структуру).

Проверяют:
- Инициализацию процесса с новой архитектурой
- Работу компонентов через композицию
- Удобные свойства для доступа
- Интеграцию всех компонентов
"""

import unittest
from multiprocessing import Queue
from multiprocess_framework.modules.Process_module.process_module import ProcessModule
from multiprocess_framework.modules.Shared_resources_module.SharedResourcesManager import SharedResourcesManager
from multiprocess_framework.modules.Config_module import ConfigManager


class TestProcessModule(unittest.TestCase):
    """Базовые тесты для ProcessModule"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.process_name = "TestProcess"
        self.shared_resources = SharedResourcesManager()
        self.config = {
            'managers': {
                'logger': {
                    'app_name': 'TestApp'
                }
            }
        }
    
    def test_process_initialization(self):
        """Тест инициализации процесса с новой архитектурой"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config=self.config
        )
        
        # Проверяем базовые атрибуты
        self.assertEqual(process.name, self.process_name)
        
        # Проверяем компоненты
        self.assertIsNotNone(process.config_handler)
        self.assertIsNotNone(process.managers_component)
        self.assertIsNotNone(process.communication)
        
        # Проверяем доступ к менеджерам через свойства
        self.assertIsNotNone(process.worker_manager)
        self.assertIsNotNone(process.logger_manager)
        self.assertIsNotNone(process.command_manager)
        self.assertIsNotNone(process.router_manager)
        
        # Проверяем регистрацию менеджеров
        self.assertIn("worker", process.managers)
        self.assertIn("logger", process.managers)
        self.assertIn("command", process.managers)
        self.assertIn("router", process.managers)
        
        # Проверяем регистрацию адаптеров
        self.assertIn("logger", process.adapters)
        self.assertIn("command", process.adapters)
        self.assertIn("router", process.adapters)
    
    def test_queues_registration(self):
        """Тест регистрации очередей"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config=self.config
        )
        
        # Проверяем наличие очередей
        self.assertIn("system", process.queues)
        self.assertIn("data", process.queues)
        self.assertIn("broadcast", process.queues)
        self.assertIn("custom", process.queues)
        
        # Проверяем регистрацию в queue_registry
        registered_processes = self.shared_resources.queue_registry.get_registered_processes()
        self.assertIn(self.process_name, registered_processes)
    
    def test_config_manager_integration(self):
        """Тест интеграции с config_manager"""
        config_manager = ConfigManager({
            'processes': {
                self.process_name: {
                    'managers': {
                        'logger': {
                            'app_name': 'ConfigApp'
                        }
                    }
                }
            }
        })
        
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config_manager=config_manager
        )
        
        # Проверяем, что конфигурация загружена через config_handler
        managers_config = process.config_handler.get_managers_config()
        self.assertIn('logger', managers_config)
        self.assertEqual(managers_config['logger']['app_name'], 'ConfigApp')
    
    def test_manager_reload(self):
        """Тест пересоздания менеджера"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config=self.config
        )
        
        # Сохраняем старый менеджер
        old_logger = process.logger_manager
        
        # Пересоздаем менеджер через managers_component
        success = process.reload_manager("logger")
        self.assertTrue(success)
        
        # Проверяем, что менеджер обновился
        self.assertIsNotNone(process.logger_manager)
        # Новый менеджер должен быть другим объектом
        self.assertNotEqual(process.logger_manager, old_logger)
    
    def test_config_update(self):
        """Тест обновления конфигурации"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config=self.config
        )
        
        new_config = {
            'managers': {
                'logger': {
                    'app_name': 'UpdatedApp'
                }
            }
        }
        
        success = process.update_config(new_config)
        self.assertTrue(success)
        # Проверяем через config_handler
        managers_config = process.config_handler.get_managers_config()
        self.assertEqual(managers_config['logger']['app_name'], 'UpdatedApp')
    
    def test_get_stats(self):
        """Тест получения статистики"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config=self.config
        )
        
        stats = process.get_stats()
        
        # Проверяем базовую структуру статистики
        self.assertEqual(stats['name'], self.process_name)
        self.assertIn('managers', stats)
        self.assertIn('adapters', stats)
        self.assertIn('queues', stats)
        self.assertIn('workers', stats)
    
    def test_send_receive_messages(self):
        """Тест отправки и получения сообщений через communication"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config=self.config
        )
        
        # Отправляем сообщение через communication
        message = {
            'type': 'test',
            'sender': self.process_name,
            'targets': [],
            'data': {'test': 'value'}
        }
        
        result = process.send(message)
        # Проверяем, что отправка прошла (может быть success или error в зависимости от конфигурации)
        self.assertIn('status', result)
        
        # Проверяем получение сообщений
        messages = process.receive(timeout=0.01)
        self.assertIsInstance(messages, list)
    
    def test_stop_process(self):
        """Тест остановки процесса"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config=self.config
        )
        
        # Запускаем процесс
        process.run()
        self.assertFalse(process.should_stop())
        
        # Останавливаем процесс
        process.stop()
        self.assertTrue(process.should_stop())
        
        # Проверяем, что процесс отменил регистрацию через communication
        registered_processes = self.shared_resources.queue_registry.get_registered_processes()
        self.assertNotIn(self.process_name, registered_processes)
    
    def test_custom_queue_registration(self):
        """Тест регистрации кастомной очереди"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config=self.config
        )
        
        custom_queue = Queue(maxsize=10)
        process.register_queue("custom_test", custom_queue)
        
        self.assertIn("custom_test", process.queues)
        self.assertEqual(process.queues["custom_test"], custom_queue)


class TestProcessModuleWithConfigManager(unittest.TestCase):
    """Тесты ProcessModule с полной интеграцией ConfigManager"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.process_name = "ConfigProcess"
        self.shared_resources = SharedResourcesManager()
        self.config_manager = ConfigManager({
            'processes': {
                self.process_name: {
                    'managers': {
                        'logger': {
                            'app_name': 'ConfigTestApp',
                            'level': 'INFO'
                        },
                        'command': {
                            'enable_logging': True
                        }
                    }
                }
            }
        })
    
    def test_config_manager_loading(self):
        """Тест загрузки конфигурации из ConfigManager"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config_manager=self.config_manager
        )
        
        # Проверяем, что конфигурация загружена через config_handler
        managers_config = process.config_handler.get_managers_config()
        self.assertIn('logger', managers_config)
        self.assertEqual(managers_config['logger']['app_name'], 'ConfigTestApp')
    
    def test_hot_reload_config(self):
        """Тест горячей перезагрузки конфигурации"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config_manager=self.config_manager
        )
        
        # Обновляем конфигурацию в config_manager
        self.config_manager.set(
            f'processes.{self.process_name}.managers.logger.app_name',
            'ReloadedApp'
        )
        
        # Перезагружаем менеджер
        success = process.reload_manager("logger")
        self.assertTrue(success)
        
        # Проверяем, что новая конфигурация применена
        managers_config = process.config_handler.get_managers_config()
        self.assertEqual(managers_config['logger']['app_name'], 'ReloadedApp')
    
    def test_component_access(self):
        """Тест доступа к компонентам через свойства"""
        process = ProcessModule(
            name=self.process_name,
            shared_resources=self.shared_resources,
            config_manager=self.config_manager
        )
        
        # Проверяем доступ к компонентам
        self.assertIsNotNone(process.config_handler)
        self.assertIsNotNone(process.managers_component)
        self.assertIsNotNone(process.communication)
        
        # Проверяем удобные свойства
        self.assertIsNotNone(process.router)
        self.assertEqual(process.router, process.router_manager)
        
        # Проверяем адаптеры
        self.assertIsNotNone(process.logger_adapter)
        self.assertIsNotNone(process.command_adapter)
        self.assertIsNotNone(process.router_adapter)


if __name__ == '__main__':
    unittest.main()

