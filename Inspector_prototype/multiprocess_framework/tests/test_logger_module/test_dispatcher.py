"""
Тесты для LogDispatcher.

Проверяет:
- Маршрутизацию логов по каналам
- Регистрацию обработчиков каналов
- Обработку ошибок
"""
import pytest
from unittest.mock import Mock

from multiprocess_framework.modules.Logger_module.dispatcher import LogDispatcher, LogRecord
from multiprocess_framework.modules.Logger_module.config import LogLevel, LogScope


class TestLogDispatcher:
    """Тесты для LogDispatcher"""
    
    @pytest.fixture
    def dispatcher(self):
        """Фикстура для LogDispatcher"""
        return LogDispatcher("test_app")
    
    @pytest.fixture
    def mock_handler(self):
        """Фикстура для mock обработчика"""
        return Mock(return_value={'status': 'success'})
    
    def test_initialization(self, dispatcher):
        """Тест инициализации диспетчера"""
        assert dispatcher.app_name == "test_app"
        assert len(dispatcher.channel_handlers) == 0
    
    def test_register_channel_handler(self, dispatcher, mock_handler):
        """Тест регистрации обработчика канала"""
        dispatcher.register_channel_handler('test_channel', mock_handler)
        
        assert 'test_channel' in dispatcher.channel_handlers
        assert dispatcher.channel_handlers['test_channel'] == mock_handler
    
    def test_route_log_single_channel(self, dispatcher, mock_handler):
        """Тест маршрутизации в один канал"""
        dispatcher.register_channel_handler('test_channel', mock_handler)
        
        record = LogRecord(
            timestamp=1234567890.0,
            level=LogLevel.INFO,
            scope=LogScope.SYSTEM,
            message='Test message',
            module='test_module',
            extra={}
        )
        
        results = dispatcher.route_log(record, ['test_channel'])
        
        assert len(results) == 1
        assert 'test_channel' in results
        assert results['test_channel']['status'] == 'success'
        mock_handler.assert_called_once()
    
    def test_route_log_multiple_channels(self, dispatcher):
        """Тест маршрутизации в несколько каналов"""
        handler1 = Mock(return_value={'status': 'success'})
        handler2 = Mock(return_value={'status': 'success'})
        
        dispatcher.register_channel_handler('channel1', handler1)
        dispatcher.register_channel_handler('channel2', handler2)
        
        record = LogRecord(
            timestamp=1234567890.0,
            level=LogLevel.INFO,
            scope=LogScope.SYSTEM,
            message='Test message',
            module='test_module',
            extra={}
        )
        
        results = dispatcher.route_log(record, ['channel1', 'channel2'])
        
        assert len(results) == 2
        assert 'channel1' in results
        assert 'channel2' in results
        handler1.assert_called_once()
        handler2.assert_called_once()
    
    def test_route_log_nonexistent_channel(self, dispatcher):
        """Тест маршрутизации в несуществующий канал"""
        record = LogRecord(
            timestamp=1234567890.0,
            level=LogLevel.INFO,
            scope=LogScope.SYSTEM,
            message='Test message',
            module='test_module',
            extra={}
        )
        
        results = dispatcher.route_log(record, ['nonexistent'])
        
        assert len(results) == 1
        assert results['nonexistent']['status'] == 'error'
        assert 'not found' in results['nonexistent']['error']
    
    def test_route_log_handler_error(self, dispatcher):
        """Тест обработки ошибки в обработчике"""
        error_handler = Mock(side_effect=Exception("Handler error"))
        dispatcher.register_channel_handler('error_channel', error_handler)
        
        record = LogRecord(
            timestamp=1234567890.0,
            level=LogLevel.INFO,
            scope=LogScope.SYSTEM,
            message='Test message',
            module='test_module',
            extra={}
        )
        
        results = dispatcher.route_log(record, ['error_channel'])
        
        assert results['error_channel']['status'] == 'error'
        assert 'error' in results['error_channel']
    
    def test_log_record_to_dict(self):
        """Тест конвертации LogRecord в словарь"""
        record = LogRecord(
            timestamp=1234567890.0,
            level=LogLevel.INFO,
            scope=LogScope.SYSTEM,
            message='Test message',
            module='test_module',
            extra={'key': 'value'}
        )
        
        record_dict = record.to_dict()
        
        assert record_dict['timestamp'] == 1234567890.0
        assert record_dict['level'] == 'INFO'
        assert record_dict['scope'] == 'system'
        assert record_dict['message'] == 'Test message'
        assert record_dict['module'] == 'test_module'
        assert record_dict['extra'] == {'key': 'value'}
