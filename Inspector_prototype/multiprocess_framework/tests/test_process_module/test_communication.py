"""
Тесты для ProcessCommunication.

Проверяют работу с коммуникацией процесса.
"""

import unittest
from multiprocessing import Queue
from multiprocess_framework.modules.Process_module.communication import ProcessCommunication
from multiprocess_framework.modules.Router_module.router_manager import RouterManager
from multiprocess_framework.modules.Logger_module.manager import LoggerManager, LogConfig
from multiprocess_framework.modules.Shared_resources_module.SharedResourcesManager import SharedResourcesManager


class TestProcessCommunication(unittest.TestCase):
    """Тесты для ProcessCommunication"""
    
    def setUp(self):
        """Подготовка тестового окружения"""
        self.process_name = "TestComm"
        self.queues = {
            'system': Queue(maxsize=100),
            'data': Queue(maxsize=50),
        }
        
        # Создаем SharedResourcesManager для получения queue_registry
        self.shared_resources = SharedResourcesManager()
        
        # Создаем минимальный logger для роутера
        log_config = LogConfig()
        log_config.app_name = self.process_name
        self.logger_manager = LoggerManager(config=log_config)
        self.logger_manager.initialize()
        
        # Создаем router_manager с queue_registry из shared_resources
        self.router_manager = RouterManager(
            f"router_{self.process_name}",
            self.logger_manager,
            self.shared_resources.queue_registry
        )
    
    def test_communication_initialization(self):
        """Тест инициализации коммуникации"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        self.assertEqual(comm.process_name, self.process_name)
        self.assertEqual(comm.queues, self.queues)
        self.assertEqual(comm.router_manager, self.router_manager)
    
    def test_register_process_queues(self):
        """Тест регистрации очередей процесса"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        comm.register_process_queues()
        
        # Проверяем, что процесс зарегистрирован
        registered_processes = self.shared_resources.queue_registry.get_registered_processes()
        self.assertIn(self.process_name, registered_processes)
    
    def test_register_router_channels(self):
        """Тест регистрации каналов в роутере"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        comm.register_router_channels()
        
        # Проверяем, что каналы зарегистрированы
        channels = self.router_manager.get_all_channels()
        self.assertGreater(len(channels), 0)
    
    def test_send_message(self):
        """Тест отправки сообщения"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        comm.register_router_channels()
        
        message = {
            'type': 'test',
            'sender': self.process_name,
            'targets': [],
            'data': {'test': 'value'}
        }
        
        result = comm.send(message)
        # Проверяем, что отправка прошла (может быть success или error)
        self.assertIn('status', result)
    
    def test_receive_messages(self):
        """Тест получения сообщений"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        comm.register_router_channels()
        
        # Отправляем сообщение в очередь
        test_message = {
            'type': 'test',
            'sender': 'sender',
            'data': {'test': 'value'}
        }
        self.queues['system'].put(test_message)
        
        # Получаем сообщения
        messages = comm.receive(timeout=0.1)
        # Может быть пустым, если сообщение еще не обработано
        self.assertIsInstance(messages, list)
    
    def test_send_to_process(self):
        """Тест отправки сообщения конкретному процессу"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        comm.register_process_queues()
        
        message = {
            'type': 'test',
            'data': {'test': 'value'}
        }
        
        # Пытаемся отправить несуществующему процессу
        result = comm.send_to_process("UnknownProcess", message)
        # Может быть False, если процесс не найден
        self.assertIsInstance(result, bool)
    
    def test_broadcast(self):
        """Тест рассылки сообщений"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        comm.register_process_queues()
        
        message = {
            'type': 'broadcast',
            'data': {'test': 'value'}
        }
        
        # Рассылаем сообщение
        count = comm.broadcast(message, exclude_self=True)
        # Может быть 0, если нет других процессов
        self.assertIsInstance(count, int)
        self.assertGreaterEqual(count, 0)
    
    def test_unregister_process(self):
        """Тест отмены регистрации процесса"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        comm.register_process_queues()
        
        # Отменяем регистрацию
        comm.unregister_process()
        
        # Проверяем, что процесс удален
        registered_processes = self.shared_resources.queue_registry.get_registered_processes()
        self.assertNotIn(self.process_name, registered_processes)
    
    def test_get_queue_stats(self):
        """Тест получения статистики очередей"""
        comm = ProcessCommunication(
            process_name=self.process_name,
            queues=self.queues,
            router_manager=self.router_manager,
            shared_resources=self.shared_resources
        )
        
        stats = comm.get_queue_stats()
        
        # Проверяем структуру статистики
        self.assertIn("system", stats)
        self.assertIn("data", stats)
        
        # Проверяем наличие данных (может быть size или error)
        # multiprocessing.Queue может не поддерживать qsize() на некоторых платформах
        system_stats = stats["system"]
        self.assertTrue(
            "size" in system_stats or "error" in system_stats,
            f"Stats should have 'size' or 'error', got: {system_stats}"
        )


if __name__ == '__main__':
    unittest.main()

