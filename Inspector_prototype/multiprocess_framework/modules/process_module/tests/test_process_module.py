"""
Юнит-тесты для ProcessModule.
"""

import pytest
import time
from unittest.mock import Mock, MagicMock
from multiprocess_framework.modules.process_module import ProcessModule


class TestProcessModule:
    """Тесты для ProcessModule."""
    
    def test_create_process(self):
        """Тест создания процесса."""
        process = ProcessModule("test_process")
        
        assert process.manager_name == "test_process"
        assert process.name == "test_process"
        assert process.is_initialized is False
    
    def test_initialize(self):
        """Тест инициализации процесса."""
        # Мокируем shared_resources
        mock_shared_resources = Mock()
        mock_shared_resources.get_process_data = Mock(return_value=None)
        mock_shared_resources.update_process_state = Mock()
        
        process = ProcessModule("test_process", shared_resources=mock_shared_resources)
        
        # Мокируем компоненты которые требуют реальных модулей
        process._init_configuration = Mock()
        process._init_queues = Mock()
        process._init_managers = Mock()
        process._init_communication = Mock()
        process._register_process_state = Mock()
        process._init_system_threads = Mock()
        process._init_custom_managers = Mock()
        process._init_application_threads = Mock()
        process.update_process_state = Mock()
        
        result = process.initialize()
        
        assert result is True
        assert process.is_initialized is True
    
    def test_shutdown(self):
        """Тест завершения процесса."""
        process = ProcessModule("test_process")
        process.is_initialized = True
        process._stop_requested = False
        
        # Мокируем компоненты
        process._stop_system_threads = Mock()
        process.worker_manager = Mock()
        process.worker_manager.stop_all_workers = Mock()
        process.logger_manager = Mock()
        process.logger_manager.shutdown = Mock()
        process.command_manager = Mock()
        process.command_manager.shutdown = Mock()
        process.router_manager = Mock()
        process.router_manager.shutdown = Mock()
        process.update_process_state = Mock()
        
        result = process.shutdown()
        
        assert result is True
        assert process.is_initialized is False
        assert process._stop_requested is True
    
    def test_run_stop(self):
        """Тест запуска и остановки процесса."""
        process = ProcessModule("test_process")
        
        # Мокируем компоненты (run/stop вызывают log -> log_info)
        process.worker_manager = Mock()
        process.worker_manager.start_all_workers = Mock()
        process.worker_manager.stop_all_workers = Mock()
        process.update_process_state = Mock()
        process.log = Mock()
        process.shutdown = Mock(return_value=True)
        
        # Запуск
        process.run()
        
        assert process._stop_requested is False
        process.worker_manager.start_all_workers.assert_called_once()
        
        # Остановка
        process.stop()
        
        assert process._stop_requested is True
    
    def test_should_stop(self):
        """Тест проверки флага остановки."""
        process = ProcessModule("test_process")
        
        assert process.should_stop() is False
        
        process._stop_requested = True
        
        assert process.should_stop() is True
    
    def test_get_config(self):
        """Тест получения конфигурации."""
        process = ProcessModule("test_process", config={"key": "value"})
        
        # Без config_handler
        value = process.get_config("key")
        assert value == "value"
        
        # С config_handler
        process.config_handler = Mock()
        process.config_handler.get = Mock(return_value="handler_value")
        
        value = process.get_config("key")
        assert value == "handler_value"
    
    def test_update_config(self):
        """Тест обновления конфигурации."""
        process = ProcessModule("test_process", config={"key": "value"})
        
        process.update_config("key", "new_value")
        
        assert process.config["key"] == "new_value"
    
    def test_managers_property(self):
        """Тест свойства managers."""
        process = ProcessModule("test_process")
        process.worker_manager = Mock()
        process.logger_manager = Mock()
        process.command_manager = Mock()
        process.router_manager = Mock()
        
        managers = process.managers
        
        assert managers['worker'] == process.worker_manager
        assert managers['logger'] == process.logger_manager
        assert managers['command'] == process.command_manager
        assert managers['router'] == process.router_manager
    
    def test_register_manager(self):
        """Тест регистрации менеджера."""
        process = ProcessModule("test_process")
        mock_manager = Mock()
        
        process.register_manager("test_manager", mock_manager)
        
        # Проверяем что менеджер зарегистрирован через ObservableMixin
        assert process.has_manager("test_manager")
        assert process.get_manager("test_manager") == mock_manager
    
    def test_get_manager(self):
        """Тест получения менеджера."""
        process = ProcessModule("test_process")
        mock_manager = Mock()
        
        process.register_manager("test_manager", mock_manager)
        
        manager = process.get_manager("test_manager")
        
        assert manager == mock_manager
    
    def test_log(self):
        """Тест логирования через ObservableMixin."""
        process = ProcessModule("test_process")
        
        # Приватные методы всегда доступны
        assert hasattr(process, '_log_info')
        assert hasattr(process, '_log_error')
        
        # Публичные прокси-методы создаются только после регистрации менеджера
        # Регистрируем mock менеджер для теста
        from unittest.mock import Mock
        mock_logger = Mock()
        process.register_manager('logger', mock_logger, enabled=True)
        
        # Теперь публичные методы должны быть доступны
        assert hasattr(process, 'log_info')
        assert hasattr(process, 'log_error')
        
        # Тест метода log() для совместимости
        process.log("INFO", "Test message", "test_context")
        # Не должно упасть
    
    def test_get_stats(self):
        """Тест получения статистики процесса."""
        process = ProcessModule("test_process")
        process.is_initialized = True
        
        # Мокируем компоненты
        process.communication = Mock()
        process.communication.get_queue_stats = Mock(return_value={})
        process.worker_manager = Mock()
        process.worker_manager.get_stats = Mock(return_value={})
        
        stats = process.get_stats()
        
        assert stats['manager_name'] == "test_process"
        assert stats['is_initialized'] is True
    
    def test_send_receive_message(self):
        """Тест отправки и получения сообщений."""
        process = ProcessModule("test_process")
        
        # Мокируем communication
        process.communication = Mock()
        process.communication.send_message = Mock(return_value=True)
        process.communication.receive_message = Mock(return_value={"data": "test"})
        
        # Отправка
        result = process.send_message("target", {"data": "test"})
        assert result is True
        
        # Получение
        message = process.receive_message(timeout=1.0)
        assert message == {"data": "test"}

