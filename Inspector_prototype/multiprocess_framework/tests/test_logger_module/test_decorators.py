"""
Тесты для декораторов логирования.

Проверяет:
- Декоратор log_call
- Декоратор log_performance
- Контекстный менеджер log_context
"""
import pytest
import time
from unittest.mock import Mock, patch

from multiprocess_framework.modules.Logger_module.decorators import (
    log_call,
    log_performance,
    log_context
)
from multiprocess_framework.modules.Logger_module.config import LogScope, LogLevel


class TestLogCallDecorator:
    """Тесты для декоратора log_call"""
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_call_basic(self, mock_get_logger):
        """Тест базового использования декоратора log_call"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        @log_call(scope=LogScope.BUSINESS, level=LogLevel.INFO)
        def test_function():
            return "result"
        
        result = test_function()
        
        assert result == "result"
        assert mock_logger.log.call_count == 2  # START и END
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_call_with_args(self, mock_get_logger):
        """Тест декоратора с логированием аргументов"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        @log_call(scope=LogScope.BUSINESS, log_args=True)
        def test_function(arg1, arg2):
            return arg1 + arg2
        
        result = test_function(1, 2)
        
        assert result == 3
        # Проверяем, что аргументы были залогированы
        log_calls = [call_args[0][2] for call_args in mock_logger.log.call_args_list]
        assert any('args' in str(log_call) for log_call in log_calls)
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_call_with_result(self, mock_get_logger):
        """Тест декоратора с логированием результата"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        @log_call(scope=LogScope.BUSINESS, log_result=True)
        def test_function():
            return "test_result"
        
        result = test_function()
        
        assert result == "test_result"
        log_calls = [call_args[0][2] for call_args in mock_logger.log.call_args_list]
        assert any('result' in str(log_call) for log_call in log_calls)
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_call_with_time(self, mock_get_logger):
        """Тест декоратора с логированием времени"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        @log_call(scope=LogScope.BUSINESS, log_time=True)
        def test_function():
            time.sleep(0.1)
            return "result"
        
        result = test_function()
        
        assert result == "result"
        log_calls = [call_args[0][2] for call_args in mock_logger.log.call_args_list]
        assert any('time' in str(log_call) for log_call in log_calls)
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_call_with_exception(self, mock_get_logger):
        """Тест декоратора при возникновении исключения"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        @log_call(scope=LogScope.BUSINESS)
        def test_function():
            raise ValueError("Test error")
        
        with pytest.raises(ValueError):
            test_function()
        
        # Должно быть залогировано исключение
        log_calls = [call_args[0][2] for call_args in mock_logger.log.call_args_list]
        assert any('ERROR' in str(log_call) for log_call in log_calls)
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_call_no_logger(self, mock_get_logger):
        """Тест декоратора когда логгер недоступен"""
        mock_get_logger.return_value = None
        
        @log_call(scope=LogScope.BUSINESS)
        def test_function():
            return "result"
        
        result = test_function()
        
        assert result == "result"


class TestLogPerformanceDecorator:
    """Тесты для декоратора log_performance"""
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_performance_slow_function(self, mock_get_logger):
        """Тест декоратора для медленной функции"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        @log_performance(threshold=0.1)
        def slow_function():
            time.sleep(0.2)
            return "result"
        
        result = slow_function()
        
        assert result == "result"
        mock_logger.log.assert_called_once()
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_performance_fast_function(self, mock_get_logger):
        """Тест декоратора для быстрой функции"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        @log_performance(threshold=0.1)
        def fast_function():
            time.sleep(0.05)
            return "result"
        
        result = fast_function()
        
        assert result == "result"
        # Быстрая функция не должна логироваться
        mock_logger.log.assert_not_called()
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_performance_no_logger(self, mock_get_logger):
        """Тест декоратора когда логгер недоступен"""
        mock_get_logger.return_value = None
        
        @log_performance(threshold=0.1)
        def test_function():
            time.sleep(0.2)
            return "result"
        
        result = test_function()
        
        assert result == "result"


class TestLogContext:
    """Тесты для контекстного менеджера log_context"""
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_context_basic(self, mock_get_logger):
        """Тест базового использования log_context"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        with log_context(user_id=123, request_id="abc-123"):
            pass
        
        mock_logger.push_context.assert_called_once_with(user_id=123, request_id="abc-123")
        mock_logger.pop_context.assert_called_once()
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_context_nested(self, mock_get_logger):
        """Тест вложенных контекстов"""
        mock_logger = Mock()
        mock_get_logger.return_value = mock_logger
        
        with log_context(user_id=123):
            with log_context(request_id="abc-123"):
                pass
        
        assert mock_logger.push_context.call_count == 2
        assert mock_logger.pop_context.call_count == 2
    
    @patch('src.Modules.Logger_module.decorators.get_logger')
    def test_log_context_no_logger(self, mock_get_logger):
        """Тест log_context когда логгер недоступен"""
        mock_get_logger.return_value = None
        
        # Не должно быть ошибок
        with log_context(user_id=123):
            pass
