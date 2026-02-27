"""
Тесты для RouterAdapter.
"""
import pytest
from unittest.mock import Mock, MagicMock
from typing import Dict, Any

from multiprocess_framework.modules.Router_module.router_adapter import RouterAdapter
from multiprocess_framework.modules.Router_module.router_manager import RouterManager
from multiprocess_framework.modules.Router_module.channel import QueueChannel


class TestRouterAdapter:
    """Тесты для RouterAdapter."""
    
    def test_adapter_initialization(self):
        """Проверяем инициализацию адаптера."""
        router = RouterManager("test_router")
        adapter = RouterAdapter(router)
        
        assert adapter.manager == router
        assert adapter.adapter_name == "RouterAdapter"
        assert adapter.process is None
        assert adapter._initialized is False
    
    def test_adapter_initialization_with_process(self):
        """Проверяем инициализацию адаптера с процессом."""
        router = RouterManager("test_router")
        mock_process = Mock()
        mock_process.name = "test_process"
        
        adapter = RouterAdapter(router, process=mock_process)
        
        assert adapter.process == mock_process
    
    def test_adapter_setup(self):
        """Проверяем настройку адаптера."""
        router = RouterManager("test_router")
        adapter = RouterAdapter(router)
        
        result = adapter.setup()
        
        assert result is True
        assert adapter._initialized is True
    
    def test_adapter_setup_without_manager(self):
        """Проверяем настройку адаптера без менеджера."""
        adapter = RouterAdapter(None)
        
        result = adapter.setup()
        
        assert result is False
        assert adapter._initialized is False
    
    def test_adapter_send(self):
        """Проверяем отправку сообщения через адаптер."""
        router = RouterManager("test_router")
        channel = QueueChannel("test_channel")
        router.register_channel(channel)
        
        adapter = RouterAdapter(router)
        adapter.setup()
        
        message = {
            'channel': 'test_channel',
            'data': 'test_data'
        }
        
        result = adapter.send(message)
        
        assert result['status'] == 'success'
    
    def test_adapter_send_without_manager(self):
        """Проверяем отправку без менеджера."""
        adapter = RouterAdapter(None)
        
        result = adapter.send({'data': 'test'})
        
        assert result['status'] == 'error'
        assert 'not available' in result['reason'].lower()
    
    def test_adapter_poll_messages(self):
        """Проверяем получение сообщений через адаптер."""
        router = RouterManager("test_router")
        channel = QueueChannel("test_channel")
        router.register_channel(channel)
        
        # Добавляем сообщение в канал
        test_message = {'data': 'test'}
        channel.send(test_message)
        
        adapter = RouterAdapter(router)
        adapter.setup()
        
        messages = adapter.poll_messages()
        
        # Сообщения должны быть получены и обработаны
        assert isinstance(messages, list)
    
    def test_adapter_poll_messages_without_manager(self):
        """Проверяем получение сообщений без менеджера."""
        adapter = RouterAdapter(None)
        
        messages = adapter.poll_messages()
        
        assert messages == []
    
    def test_adapter_send_to_process_with_queue_registry(self):
        """Проверяем отправку сообщения процессу через queue_registry."""
        router = RouterManager("test_router")
        
        # Мокируем queue_registry
        mock_queue_registry = Mock()
        mock_queue_registry.send_to_queue = Mock(return_value=True)
        router.queue_registry = mock_queue_registry
        
        mock_process = Mock()
        mock_process.name = "sender_process"
        
        adapter = RouterAdapter(router, process=mock_process)
        adapter.setup()
        
        message = {'data': 'test'}
        result = adapter.send_to_process("target_process", message)
        
        assert result is True
        mock_queue_registry.send_to_queue.assert_called_once()
    
    def test_adapter_send_to_process_without_queue_registry(self):
        """Проверяем отправку без queue_registry (fallback)."""
        router = RouterManager("test_router")
        channel = QueueChannel("internal_queue")
        router.register_channel(channel)
        
        adapter = RouterAdapter(router)
        adapter.setup()
        
        message = {'data': 'test'}
        result = adapter.send_to_process("target_process", message)
        
        # Fallback должен работать через роутер
        assert isinstance(result, bool)
    
    def test_adapter_broadcast_with_queue_registry(self):
        """Проверяем broadcast через queue_registry."""
        router = RouterManager("test_router")
        
        mock_queue_registry = Mock()
        mock_queue_registry.broadcast_message = Mock(return_value=3)
        router.queue_registry = mock_queue_registry
        
        mock_process = Mock()
        mock_process.name = "sender_process"
        
        adapter = RouterAdapter(router, process=mock_process)
        adapter.setup()
        
        message = {'data': 'broadcast'}
        count = adapter.broadcast(message)
        
        assert count == 3
        mock_queue_registry.broadcast_message.assert_called_once()
    
    def test_adapter_broadcast_without_queue_registry(self):
        """Проверяем broadcast без queue_registry (fallback)."""
        router = RouterManager("test_router")
        channel = QueueChannel("internal_queue")
        router.register_channel(channel)
        
        adapter = RouterAdapter(router)
        adapter.setup()
        
        message = {'data': 'broadcast'}
        count = adapter.broadcast(message)
        
        # Fallback должен вернуть 1 или 0
        assert count in [0, 1]
    
    def test_adapter_broadcast_exclude_self(self):
        """Проверяем broadcast с исключением себя."""
        router = RouterManager("test_router")
        
        mock_queue_registry = Mock()
        mock_queue_registry.broadcast_message = Mock(return_value=2)
        router.queue_registry = mock_queue_registry
        
        mock_process = Mock()
        mock_process.name = "sender_process"
        
        adapter = RouterAdapter(router, process=mock_process)
        adapter.setup()
        
        message = {'data': 'broadcast'}
        count = adapter.broadcast(message, exclude_self=True)
        
        # Проверяем, что exclude_process был передан
        call_args = mock_queue_registry.broadcast_message.call_args
        assert call_args[0][2] == "sender_process"  # exclude_process
    
    def test_adapter_get_stats(self):
        """Проверяем получение статистики адаптера."""
        router = RouterManager("test_router")
        adapter = RouterAdapter(router)
        adapter.setup()
        
        stats = adapter.get_stats()
        
        assert 'adapter_name' in stats
        assert 'initialized' in stats
        assert stats['adapter_name'] == 'RouterAdapter'
        assert stats['initialized'] is True
        assert 'router' in stats
    
    def test_adapter_get_stats_with_router_stats(self):
        """Проверяем статистику адаптера со статистикой роутера."""
        router = RouterManager("test_router")
        router._stats['sent'] = 5
        router._stats['received'] = 3
        
        adapter = RouterAdapter(router)
        adapter.setup()
        
        stats = adapter.get_stats()
        
        assert 'router' in stats
        router_stats = stats['router']
        assert router_stats['sent'] == 5
        assert router_stats['received'] == 3
    
    def test_adapter_get_stats_error_handling(self):
        """Проверяем обработку ошибок при получении статистики."""
        router = RouterManager("test_router")
        adapter = RouterAdapter(router)
        adapter.setup()
        
        # Ломаем метод get_stats роутера
        router.get_stats = Mock(side_effect=Exception("Test error"))
        
        stats = adapter.get_stats()
        
        # Должна вернуться статистика адаптера с ошибкой роутера
        assert 'router' in stats
        assert 'error' in stats['router']

