"""
Тесты для новых методов ProcessManager.

Проверяют:
- process_monitor интеграцию
- console_manager интеграцию
- новые методы регистрации с расширенными параметрами
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from multiprocess_framework.modules.Process_manager_module import ProcessManager
from multiprocess_framework.modules.Process_module.process_module import ProcessModule


class TestProcessManagerNewFeatures:
    """Тесты для новых функций ProcessManager"""
    
    @pytest.fixture
    def process_manager(self):
        """Фикстура для ProcessManager"""
        return ProcessManager()
    
    def test_process_monitor_initialization(self, process_manager):
        """Тест инициализации ProcessMonitor"""
        assert process_manager.process_monitor is not None
        assert process_manager.process_monitor.shared_resources is process_manager.shared_resources
        assert process_manager.process_monitor.stop_event is process_manager.stop_event
    
    def test_console_manager_initialization(self, process_manager):
        """Тест инициализации ConsoleManager"""
        assert process_manager.console_manager is not None
    
    def test_register_process_with_console_config(self, process_manager):
        """Тест регистрации процесса с конфигурацией консоли"""
        result = process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule",
            console_config={
                "enabled": True,
                "title": "Test Process Console",
                "recipient": "main_console"
            }
        )
        
        assert result is True
        
        # Проверяем что консоль настроена
        config = process_manager.get_process_config()
        assert "console" in config["test_process"]
        assert config["test_process"]["console"]["enabled"] is True
        assert config["test_process"]["console"]["title"] == "Test Process Console"
    
    def test_register_process_with_queue_config(self, process_manager):
        """Тест регистрации процесса с конфигурацией очередей"""
        result = process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule",
            queue_config={
                "system": {"maxsize": 100},
                "data": {"maxsize": 50}
            }
        )
        
        assert result is True
        
        # Проверяем что очереди настроены
        config = process_manager.get_process_config()
        assert "queues" in config["test_process"]
        assert "system" in config["test_process"]["queues"]
        assert "data" in config["test_process"]["queues"]
        assert config["test_process"]["queues"]["system"]["maxsize"] == 100
    
    def test_register_process_with_all_configs(self, process_manager):
        """Тест регистрации процесса со всеми конфигурациями"""
        result = process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule",
            config={"key": "value"},
            priority="high",
            enabled=True,
            console_config={
                "enabled": True,
                "title": "Test Console"
            },
            queue_config={
                "system": {"maxsize": 100}
            }
        )
        
        assert result is True
        
        config = process_manager.get_process_config()
        process_config = config["test_process"]
        
        assert process_config["priority"] == "high"
        assert process_config["enabled"] is True
        assert process_config["config"]["key"] == "value"
        assert "console" in process_config
        assert "queues" in process_config
    
    def test_register_queue_for_existing_process(self, process_manager):
        """Тест регистрации очереди для существующего процесса"""
        # Сначала регистрируем процесс
        process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule"
        )
        
        # Затем регистрируем очередь
        result = process_manager.register_queue(
            process_name="test_process",
            queue_name="new_queue",
            maxsize=200
        )
        
        assert result is True
        
        config = process_manager.get_process_config()
        assert "new_queue" in config["test_process"]["queues"]
        assert config["test_process"]["queues"]["new_queue"]["maxsize"] == 200
    
    def test_register_queue_for_nonexistent_process(self, process_manager):
        """Тест регистрации очереди для несуществующего процесса"""
        result = process_manager.register_queue(
            process_name="nonexistent_process",
            queue_name="test_queue",
            maxsize=100
        )
        
        assert result is False
    
    def test_register_worker_with_class_path(self, process_manager):
        """Тест регистрации воркера с путем к классу"""
        # Сначала регистрируем процесс
        process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule"
        )
        
        # Регистрируем воркера
        result = process_manager.register_worker(
            process_name="test_process",
            worker_name="test_worker",
            worker_class_path="TestModule.TestWorker",
            config={"interval": 1.0},
            priority="high",
            auto_start=True
        )
        
        assert result is True
        
        config = process_manager.get_process_config()
        assert "workers" in config["test_process"]
        assert "test_worker" in config["test_process"]["workers"]
        worker_config = config["test_process"]["workers"]["test_worker"]
        assert worker_config["class"] == "TestModule.TestWorker"
        assert worker_config["priority"] == "high"
        assert worker_config["auto_start"] is True
    
    def test_register_worker_for_nonexistent_process(self, process_manager):
        """Тест регистрации воркера для несуществующего процесса"""
        result = process_manager.register_worker(
            process_name="nonexistent_process",
            worker_name="test_worker",
            worker_class_path="TestModule.TestWorker"
        )
        
        # Должен вернуть True, но сохранить в конфиг для будущего использования
        assert result is True
    
    def test_process_monitor_start_stop(self, process_manager):
        """Тест запуска и остановки ProcessMonitor"""
        monitor = process_manager.process_monitor
        
        # Запускаем мониторинг
        monitor.start()
        assert monitor._monitoring is True
        
        # Останавливаем мониторинг
        monitor.stop()
        assert monitor._monitoring is False
    
    def test_console_manager_configure_process(self, process_manager):
        """Тест настройки консоли для процесса"""
        # Регистрируем процесс с консолью
        process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule",
            console_config={
                "enabled": True,
                "title": "Test Console",
                "recipient": "main"
            }
        )
        
        # Проверяем что консоль настроена
        status = process_manager.console_manager.get_status("test_process")
        assert status is not None
    
    def test_platform_adapter_integration(self, process_manager):
        """Тест интеграции с платформенным адаптером"""
        assert process_manager.platform is not None
        
        # Проверяем что можем получить приоритеты
        priority_map = process_manager.platform.get_priority_map()
        assert isinstance(priority_map, dict)
        assert 'normal' in priority_map
    
    def test_shared_resources_integration(self, process_manager):
        """Тест интеграции с SharedResourcesManager"""
        assert process_manager.shared_resources is not None
        
        # Проверяем что можем регистрировать процесс
        process_manager.shared_resources.register_process_with_config(
            process_name="test_process",
            config=None,
            initial_state={"status": "test"}
        )
        
        # Проверяем что можем получить состояние
        state = process_manager.shared_resources.get_process_state("test_process")
        assert state is not None
        assert state["status"] == "test"
    
    def test_queue_registry_integration(self, process_manager):
        """Тест интеграции с QueueRegistry"""
        assert process_manager.queue_registry is not None
        
        # Регистрируем процесс с очередями
        process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule",
            queue_config={
                "system": {"maxsize": 100}
            }
        )
        
        # Проверяем что очереди созданы
        queues = process_manager.queue_registry.get_process_queues("test_process")
        assert queues is not None


class TestProcessManagerExtendedRegistration:
    """Расширенные тесты регистрации"""
    
    @pytest.fixture
    def process_manager(self):
        """Фикстура для ProcessManager"""
        return ProcessManager()
    
    def test_register_multiple_processes(self, process_manager):
        """Тест регистрации нескольких процессов"""
        processes = [
            {
                "name": "process1",
                "class_path": "src.Modules.Process_module.process_module.ProcessModule",
                "priority": "high"
            },
            {
                "name": "process2",
                "class_path": "src.Modules.Process_module.process_module.ProcessModule",
                "priority": "normal"
            },
            {
                "name": "process3",
                "class_path": "src.Modules.Process_module.process_module.ProcessModule",
                "priority": "low"
            }
        ]
        
        for proc in processes:
            result = process_manager.register_process(**proc)
            assert result is True
        
        config = process_manager.get_process_config()
        assert len(config) == 3
        assert config["process1"]["priority"] == "high"
        assert config["process2"]["priority"] == "normal"
        assert config["process3"]["priority"] == "low"
    
    def test_register_multiple_queues(self, process_manager):
        """Тест регистрации нескольких очередей для процесса"""
        process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule"
        )
        
        queues = [
            ("queue1", 100),
            ("queue2", 200),
            ("queue3", 300)
        ]
        
        for queue_name, maxsize in queues:
            result = process_manager.register_queue("test_process", queue_name, maxsize)
            assert result is True
        
        config = process_manager.get_process_config()
        assert len(config["test_process"]["queues"]) == 3
    
    def test_register_multiple_workers(self, process_manager):
        """Тест регистрации нескольких воркеров для процесса"""
        process_manager.register_process(
            name="test_process",
            class_path="src.Modules.Process_module.process_module.ProcessModule"
        )
        
        workers = [
            {
                "worker_name": "worker1",
                "worker_class_path": "TestModule.Worker1",
                "priority": "high"
            },
            {
                "worker_name": "worker2",
                "worker_class_path": "TestModule.Worker2",
                "priority": "normal"
            }
        ]
        
        for worker in workers:
            result = process_manager.register_worker(
                process_name="test_process",
                **worker
            )
            assert result is True
        
        config = process_manager.get_process_config()
        assert len(config["test_process"]["workers"]) == 2

