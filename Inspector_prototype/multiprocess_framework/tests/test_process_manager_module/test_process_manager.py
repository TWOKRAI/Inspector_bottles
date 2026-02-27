"""
Тесты для ProcessManager.

Проверяют главный класс менеджера процессов.
"""

import unittest
from multiprocessing import Event
from multiprocess_framework.modules.Process_manager_module import ProcessManager
from multiprocess_framework.modules.Process_module.process_module import ProcessModule
from multiprocess_framework.modules.Logger_module import LoggerManager


class TestProcessManager(unittest.TestCase):
    """Тесты для ProcessManager"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.manager = ProcessManager()
    
    def tearDown(self):
        """Очистка после тестов"""
        # Останавливаем все процессы
        if hasattr(self.manager, 'lifecycle') and self.manager.lifecycle.os_processes:
            self.manager.stop_processes()
            self.manager.join_processes(timeout=1.0)
    
    def test_manager_initialization(self):
        """Тест инициализации менеджера"""
        self.assertIsNotNone(self.manager.stop_event)
        self.assertIsNotNone(self.manager.config_manager)
        self.assertIsNotNone(self.manager.logger)
        self.assertIsInstance(self.manager.logger, LoggerManager)
        self.assertIsNotNone(self.manager.lifecycle)
        self.assertIsNotNone(self.manager.priority)
        self.assertIsNotNone(self.manager.shared_resources)
        self.assertIsNotNone(self.manager.status)
    
    def test_load_config(self):
        """Тест загрузки конфигурации"""
        process_config = {
            'TestProcess': {
                'class': 'src.Modules.Process_module.process_module.ProcessModule',
                'priority': 'normal',
                'enabled': True,
                'config': {}
            }
        }
        
        config = self.manager.load_config(process_config)
        
        self.assertIsInstance(config, dict)
        self.assertIn('TestProcess', config)
        # После загрузки класс должен быть заменен на объект класса
        self.assertNotIsInstance(config['TestProcess']['class'], str)
    
    def test_load_config_with_dict_class(self):
        """Тест загрузки конфигурации с уже загруженным классом"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'priority': 'normal',
                'enabled': True,
                'config': {}
            }
        }
        
        config = self.manager.load_config(process_config)
        
        self.assertIsInstance(config, dict)
        self.assertIn('TestProcess', config)
        self.assertEqual(config['TestProcess']['class'], ProcessModule)
    
    def test_initialize_processes(self):
        """Тест инициализации процессов"""
        process_config = {
            'TestProcess1': {
                'class': ProcessModule,
                'priority': 'normal',
                'enabled': True,
                'config': {}
            },
            'TestProcess2': {
                'class': ProcessModule,
                'priority': 'high',
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        # Проверяем, что процессы созданы
        self.assertEqual(len(self.manager.os_processes), 2)
        
        # Проверяем статус
        self.assertIsNotNone(self.manager.status)
        self.assertEqual(len(self.manager.status.processes), 2)
    
    def test_initialize_processes_disabled(self):
        """Тест инициализации с отключенными процессами"""
        process_config = {
            'EnabledProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            },
            'DisabledProcess': {
                'class': ProcessModule,
                'enabled': False,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        # Должен быть создан только один процесс
        self.assertEqual(len(self.manager.os_processes), 1)
    
    def test_get_process_status(self):
        """Тест получения статуса процессов"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        status = self.manager.get_process_status()
        
        self.assertIsInstance(status, dict)
        # Статус может быть пустым если процессы не запущены
        if status:
            # Проверяем структуру статуса
            for process_name, process_status in status.items():
                self.assertIsInstance(process_status, dict)
    
    def test_get_stats(self):
        """Тест получения статистики"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        stats = self.manager.get_stats()
        
        self.assertIn('processes', stats)
        self.assertIn('process_count', stats)
        self.assertIn('config_manager', stats)
        self.assertIn('shared_resources', stats)
        
        # Проверяем структуру config_manager статистики
        config_stats = stats['config_manager']
        self.assertIn('total_configs', config_stats)
        self.assertIn('processes_config_loaded', config_stats)
        self.assertIn('processes_in_config', config_stats)
        self.assertIn('enabled_processes', config_stats)
    
    def test_os_processes_property(self):
        """Тест свойства os_processes"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        processes = self.manager.os_processes
        self.assertIsInstance(processes, list)
        self.assertEqual(len(processes), 1)
    
    def test_get_process_config(self):
        """Тест получения конфигурации процессов"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {'test': 'value'}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        config = self.manager.get_process_config()
        
        self.assertIsInstance(config, dict)
        self.assertIn('TestProcess', config)
    
    def test_start_processes(self):
        """Тест запуска процессов"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        # Запускаем процессы
        self.manager.start_processes()
        
        # Проверяем, что процессы запущены
        import time
        time.sleep(0.1)  # Даем время на запуск
        
        # Процессы должны быть живы (если они не завершились сразу)
        # Проверяем что метод выполнился без ошибок
        self.assertIsNotNone(self.manager.lifecycle.os_processes)
    
    def test_stop_processes(self):
        """Тест остановки процессов"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        self.manager.start_processes()
        
        import time
        time.sleep(0.1)
        
        # Останавливаем процессы
        self.manager.stop_processes()
        
        # Проверяем что метод выполнился без ошибок
        self.assertIsNotNone(self.manager.lifecycle.os_processes)
    
    def test_is_running_property(self):
        """Тест свойства is_running"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        # До запуска должно быть False
        self.assertFalse(self.manager.is_running)
        
        # После запуска может быть True (если процесс не завершился сразу)
        self.manager.start_processes()
        import time
        time.sleep(0.1)
        
        # Проверяем что свойство работает
        running = self.manager.is_running
        self.assertIsInstance(running, bool)
    
    def test_logger_integration(self):
        """Тест интеграции с LoggerManager"""
        self.assertIsNotNone(self.manager.logger)
        self.assertIsInstance(self.manager.logger, LoggerManager)
        
        # Проверяем что logger инициализирован
        self.assertTrue(self.manager.logger.is_initialized)
    
    def test_load_config_empty(self):
        """Тест загрузки пустой конфигурации"""
        config = self.manager.load_config({})
        self.assertIsInstance(config, dict)
    
    def test_load_config_none(self):
        """Тест загрузки конфигурации None"""
        config = self.manager.load_config(None)
        # Может вернуть пустой dict или дефолтную конфигурацию
        self.assertIsInstance(config, dict)
    
    def test_load_process_class_from_string(self):
        """Тест загрузки класса процесса из строки"""
        class_path = 'src.Modules.Process_module.process_module.ProcessModule'
        process_class = self.manager._load_process_class(class_path)
        
        self.assertIsNotNone(process_class)
        self.assertEqual(process_class, ProcessModule)
        
        # Проверяем кэш
        self.assertIn(class_path, self.manager._process_classes_cache)
    
    def test_load_process_class_invalid(self):
        """Тест загрузки несуществующего класса"""
        class_path = 'invalid.module.NonExistentClass'
        process_class = self.manager._load_process_class(class_path)
        
        self.assertIsNone(process_class)
    
    def test_load_process_class_cached(self):
        """Тест использования кэша при загрузке класса"""
        class_path = 'src.Modules.Process_module.process_module.ProcessModule'
        
        # Первая загрузка
        process_class1 = self.manager._load_process_class(class_path)
        
        # Вторая загрузка должна использовать кэш
        process_class2 = self.manager._load_process_class(class_path)
        
        self.assertEqual(process_class1, process_class2)
        self.assertEqual(process_class1, ProcessModule)
    
    def test_initialize_processes_with_invalid_class(self):
        """Тест инициализации с невалидным классом"""
        process_config = {
            'InvalidProcess': {
                'class': 'invalid.module.NonExistentClass',
                'enabled': True,
                'config': {}
            }
        }
        
        # Не должно вызвать исключение, но процесс не должен быть создан
        self.manager.initialize_processes(process_config)
        
        # Процесс с невалидным классом не должен быть создан
        self.assertEqual(len(self.manager.os_processes), 0)
    
    def test_initialize_processes_with_missing_class(self):
        """Тест инициализации без указания класса"""
        process_config = {
            'ProcessWithoutClass': {
                'enabled': True,
                'config': {}
            }
        }
        
        # Не должно вызвать исключение
        self.manager.initialize_processes(process_config)
        
        # Процесс без класса не должен быть создан
        self.assertEqual(len(self.manager.os_processes), 0)
    
    def test_initialize_processes_with_queues(self):
        """Тест инициализации процессов с очередями"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {},
                'queues': {
                    'input': {'maxsize': 100},
                    'output': {'maxsize': 100}
                }
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        # Проверяем что очереди зарегистрированы
        queues = self.manager.shared_resources.queue_registry.get_process_queues('TestProcess')
        self.assertIsNotNone(queues)
        self.assertGreater(len(queues), 0)
    
    def test_join_processes(self):
        """Тест ожидания завершения процессов"""
        process_config = {
            'TestProcess': {
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        self.manager.start_processes()
        
        import time
        time.sleep(0.1)
        
        # Останавливаем процессы
        self.manager.stop_processes()
        
        # Ожидаем завершения
        self.manager.join_processes(timeout=1.0)
        
        # Проверяем что метод выполнился без ошибок
        self.assertIsNotNone(self.manager.lifecycle.os_processes)
    
    def test_get_process_status_empty(self):
        """Тест получения статуса когда нет процессов"""
        status = self.manager.get_process_status()
        
        self.assertIsInstance(status, dict)
        # Может быть пустым если нет процессов
        self.assertIsInstance(status, dict)
    
    def test_get_process_config_empty(self):
        """Тест получения конфигурации когда нет процессов"""
        config = self.manager.get_process_config()
        
        self.assertIsInstance(config, dict)
    
    def test_start_processes_empty(self):
        """Тест запуска когда нет процессов"""
        # Не должно вызвать исключение
        self.manager.start_processes()
        
        # Проверяем что метод выполнился
        self.assertEqual(len(self.manager.os_processes), 0)
    
    def test_stop_processes_empty(self):
        """Тест остановки когда нет процессов"""
        # Не должно вызвать исключение
        self.manager.stop_processes()
        
        # Проверяем что метод выполнился
        self.assertEqual(len(self.manager.os_processes), 0)
    
    def test_load_and_replace_process_classes(self):
        """Тест замены строк на классы в конфигурации"""
        config_data = {
            'TestProcess': {
                'class': 'src.Modules.Process_module.process_module.ProcessModule',
                'enabled': True
            }
        }
        
        # Вызываем приватный метод через публичный load_config
        result = self.manager.load_config(config_data)
        
        # Класс должен быть заменен на объект класса
        self.assertNotIsInstance(result['TestProcess']['class'], str)
        self.assertEqual(result['TestProcess']['class'], ProcessModule)
    
    def test_initialize_processes_with_name_override(self):
        """Тест инициализации с переопределением имени процесса"""
        process_config = {
            'ConfigName': {
                'name': 'ActualProcessName',
                'class': ProcessModule,
                'enabled': True,
                'config': {}
            }
        }
        
        self.manager.initialize_processes(process_config)
        
        # Проверяем что процесс создан с правильным именем
        self.assertEqual(len(self.manager.os_processes), 1)
        self.assertEqual(self.manager.os_processes[0].name, 'ActualProcessName')


if __name__ == '__main__':
    unittest.main()

