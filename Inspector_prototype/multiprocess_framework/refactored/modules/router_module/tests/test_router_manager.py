"""
Тесты для RouterManager.

Проверяет основную функциональность роутера:
- Инициализация и завершение работы
- Регистрация каналов
- Отправка и получение сообщений
- Интеграция с Dispatch модулем
"""

import unittest
from queue import Queue
from typing import Dict, Any

from ..core.router_manager import RouterManager
from ..channels.queue_channel import QueueChannel
from ...dispatch_module import DispatchStrategy


class TestRouterManager(unittest.TestCase):
    """Тесты для RouterManager."""
    
    def setUp(self):
        """Подготовка тестового окружения."""
        self.router = RouterManager(
            manager_name="test_router",
            dispatch_strategy=DispatchStrategy.EXACT_MATCH
        )
        self.router.initialize()
        
        # Создаем тестовый канал
        self.test_queue = Queue()
        self.channel = QueueChannel("test_channel", self.test_queue)
        self.router.register_channel(self.channel)
    
    def tearDown(self):
        """Очистка после тестов."""
        if self.router:
            self.router.shutdown()
    
    def test_initialization(self):
        """Тест инициализации роутера."""
        self.assertTrue(self.router.is_initialized)
        self.assertEqual(self.router.manager_name, "test_router")
        self.assertEqual(self.router.router_id, "test_router")
    
    def test_channel_registration(self):
        """Тест регистрации канала."""
        new_channel = QueueChannel("new_channel", Queue())
        result = self.router.register_channel(new_channel)
        
        self.assertTrue(result)
        self.assertIsNotNone(self.router.get_channel("new_channel"))
        self.assertEqual(len(self.router.get_all_channels()), 2)
    
    def test_channel_unregistration(self):
        """Тест удаления канала."""
        result = self.router.unregister_channel("test_channel")
        
        self.assertTrue(result)
        self.assertIsNone(self.router.get_channel("test_channel"))
        self.assertEqual(len(self.router.get_all_channels()), 0)
    
    def test_send_message(self):
        """Тест отправки сообщения."""
        message = {
            'type': 'command',
            'command': 'test_command',
            'data': {'test': 'data'}
        }
        
        result = self.router.send(message)
        
        self.assertEqual(result['status'], 'success')
        self.assertFalse(self.test_queue.empty())
        
        # Проверяем, что сообщение попало в очередь
        received_message = self.test_queue.get()
        self.assertEqual(received_message['command'], 'test_command')
    
    def test_receive_message(self):
        """Тест получения сообщения."""
        # Отправляем сообщение напрямую в очередь
        test_message = {
            'type': 'command',
            'command': 'test_receive',
            'data': {'test': 'receive'}
        }
        self.test_queue.put(test_message)
        
        # Получаем сообщения через роутер
        messages = self.router.receive(timeout=0.1)
        
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['command'], 'test_receive')
    
    def test_channel_handler_registration(self):
        """Тест регистрации обработчика канала."""
        def custom_handler(message: Dict[str, Any]) -> Dict[str, Any]:
            return {'status': 'success', 'channel': 'custom_channel'}
        
        result = self.router.register_channel_handler(
            key='custom_key',
            handler=custom_handler,
            efficiency=10
        )
        
        self.assertTrue(result)
        
        # Проверяем, что обработчик зарегистрирован
        stats = self.router.get_stats()
        self.assertGreaterEqual(stats['router']['channel_handlers'], 1)
    
    def test_message_handler_registration(self):
        """Тест регистрации обработчика сообщений."""
        def message_handler(message: Dict[str, Any]) -> Dict[str, Any]:
            return {'status': 'processed', 'result': message.get('data')}
        
        result = self.router.register_message_handler(
            key='process_message',
            handler=message_handler
        )
        
        self.assertTrue(result)
        
        # Проверяем, что обработчик зарегистрирован
        stats = self.router.get_stats()
        self.assertGreaterEqual(stats['router']['message_handlers'], 1)
    
    def test_default_handlers(self):
        """Тест обработчиков по умолчанию."""
        # Проверяем наличие обработчиков по умолчанию
        dispatcher_info = self.router.get_dispatcher_info()
        
        channel_handlers = dispatcher_info['channel_dispatcher']['handlers']
        handler_keys = [h['key'] for h in channel_handlers]
        
        self.assertIn('log_message', handler_keys)
        self.assertIn('broadcast_message', handler_keys)
        self.assertIn('default_queue', handler_keys)
    
    def test_log_message_routing(self):
        """Тест маршрутизации логических сообщений."""
        message = {
            'type': 'log',
            'level': 'info',
            'message': 'Test log message'
        }
        
        result = self.router.send(message)
        
        # Должно быть успешно обработано
        self.assertEqual(result['status'], 'success')
    
    def test_broadcast_message_routing(self):
        """Тест маршрутизации широковещательных сообщений."""
        message = {
            'type': 'broadcast',
            'targets': ['all'],
            'data': {'message': 'Broadcast test'}
        }
        
        result = self.router.send(message)
        
        # Должно быть успешно обработано
        self.assertEqual(result['status'], 'success')
    
    def test_stats(self):
        """Тест получения статистики."""
        # Отправляем несколько сообщений
        for i in range(5):
            self.router.send({
                'type': 'command',
                'command': f'test_{i}',
                'data': {}
            })
        
        stats = self.router.get_stats()
        
        self.assertIn('router', stats)
        router_stats = stats['router']
        self.assertEqual(router_stats['sent'], 5)
        self.assertGreaterEqual(router_stats['channels_count'], 1)
    
    def test_shutdown(self):
        """Тест завершения работы роутера."""
        result = self.router.shutdown()
        
        self.assertTrue(result)
        self.assertFalse(self.router.is_initialized)
        self.assertEqual(len(self.router.get_all_channels()), 0)


if __name__ == '__main__':
    unittest.main()

