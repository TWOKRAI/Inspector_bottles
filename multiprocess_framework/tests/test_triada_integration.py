"""
Интеграционные тесты для "Тройцы создания циклов".

Тестирует взаимодействие трех главных классов:
1. ProcessManagerCore (Сверхэго) - управляет всеми процессами системы
2. ProcessModule (Эго) - базовый процесс, выполняет работу
3. WorkerManager (Ид) - управляет потоками внутри процесса
"""

import time
from unittest.mock import Mock

from multiprocess_framework.modules.process_manager_module import ProcessManagerCore
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import WorkerManager, ThreadConfig, ThreadPriority


class TestTriadaIntegration:
    """Интеграционные тесты для Тройцы."""

    def test_triada_initialization(self):
        """Тест инициализации всех трех классов Тройцы."""
        # 1. ProcessManagerCore (Сверхэго)
        mock_shared_resources = Mock()
        mock_queue_registry = Mock()
        mock_config_manager = Mock()
        mock_console_manager = Mock()
        mock_platform = Mock()
        mock_platform.setup_multiprocessing = Mock()

        process_manager = ProcessManagerCore(
            manager_name="TestProcessManager",
            shared_resources=mock_shared_resources,
            queue_registry=mock_queue_registry,
            config_manager=mock_config_manager,
            console_manager=mock_console_manager,
            platform_adapter=mock_platform,
        )

        assert process_manager.initialize() is True
        assert process_manager.is_initialized is True

        # 2. ProcessModule (Эго)
        process_module = ProcessModule("TestProcess", shared_resources=mock_shared_resources)

        # Мокируем компоненты
        process_module._init_configuration = Mock()
        process_module._init_queues = Mock()
        process_module._init_managers = Mock()
        process_module._init_communication = Mock()
        process_module._register_process_state = Mock()
        process_module._init_system_threads = Mock()
        process_module._init_custom_managers = Mock()
        process_module._init_application_threads = Mock()
        process_module.update_process_state = Mock()

        assert process_module.initialize() is True
        assert process_module.is_initialized is True

        # 3. WorkerManager (Ид)
        worker_manager = WorkerManager("TestProcess")
        assert worker_manager.initialize() is True
        assert worker_manager.is_initialized is True

        # Проверяем что все наследуются от BaseManager
        assert hasattr(process_manager, "initialize")
        assert hasattr(process_manager, "shutdown")
        assert hasattr(process_module, "initialize")
        assert hasattr(process_module, "shutdown")
        assert hasattr(worker_manager, "initialize")
        assert hasattr(worker_manager, "shutdown")

    def test_triada_lifecycle(self):
        """Тест жизненного цикла Тройцы."""
        # 1. ProcessManagerCore
        mock_shared_resources = Mock()
        mock_queue_registry = Mock()
        mock_config_manager = Mock()
        mock_console_manager = Mock()
        mock_platform = Mock()
        mock_platform.setup_multiprocessing = Mock()

        process_manager = ProcessManagerCore(
            manager_name="TestProcessManager",
            shared_resources=mock_shared_resources,
            queue_registry=mock_queue_registry,
            config_manager=mock_config_manager,
            console_manager=mock_console_manager,
            platform_adapter=mock_platform,
        )
        process_manager.initialize()

        # 2. ProcessModule
        process_module = ProcessModule("TestProcess", shared_resources=mock_shared_resources)
        process_module._init_configuration = Mock()
        process_module._init_queues = Mock()
        process_module._init_managers = Mock()
        process_module._init_communication = Mock()
        process_module._register_process_state = Mock()
        process_module._init_system_threads = Mock()
        process_module._init_custom_managers = Mock()
        process_module._init_application_threads = Mock()
        process_module.update_process_state = Mock()
        process_module.initialize()

        # 3. WorkerManager
        worker_manager = WorkerManager("TestProcess")
        worker_manager.initialize()

        # Завершение всех
        assert process_manager.shutdown() is True
        assert process_module.shutdown() is True
        assert worker_manager.shutdown() is True

        assert process_manager.is_initialized is False
        assert process_module.is_initialized is False
        assert worker_manager.is_initialized is False

    def test_process_module_uses_worker_manager(self):
        """Тест что ProcessModule использует WorkerManager."""
        mock_shared_resources = Mock()

        process_module = ProcessModule("TestProcess", shared_resources=mock_shared_resources)

        # Мокируем компоненты
        process_module._init_configuration = Mock()
        process_module._init_queues = Mock()
        process_module._init_managers = Mock()
        process_module._init_communication = Mock()
        process_module._register_process_state = Mock()
        process_module._init_system_threads = Mock()
        process_module._init_custom_managers = Mock()
        process_module._init_application_threads = Mock()
        process_module.update_process_state = Mock()

        # Создаем WorkerManager вручную
        worker_manager = WorkerManager("TestProcess")
        worker_manager.initialize()
        process_module.worker_manager = worker_manager

        # Проверяем что ProcessModule может использовать WorkerManager
        def worker_func(stop_event, pause_event):
            while not stop_event.is_set():
                time.sleep(0.1)

        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        assert process_module.worker_manager.create_worker("test_worker", worker_func, config) is True
        assert process_module.worker_manager.has_worker("test_worker")

        # Очистка
        process_module.worker_manager.stop_all_workers()
        process_module.worker_manager.shutdown()

    def test_triada_stats(self):
        """Тест статистики всех трех классов."""
        # 1. ProcessManagerCore
        mock_shared_resources = Mock()
        mock_queue_registry = Mock()
        mock_config_manager = Mock()
        mock_console_manager = Mock()
        mock_platform = Mock()
        mock_platform.setup_multiprocessing = Mock()

        process_manager = ProcessManagerCore(
            manager_name="TestProcessManager",
            shared_resources=mock_shared_resources,
            queue_registry=mock_queue_registry,
            config_manager=mock_config_manager,
            console_manager=mock_console_manager,
            platform_adapter=mock_platform,
        )
        process_manager.initialize()

        stats = process_manager.get_stats()
        assert "manager_name" in stats
        assert "is_initialized" in stats
        assert "processes" in stats

        # 2. ProcessModule
        process_module = ProcessModule("TestProcess", shared_resources=mock_shared_resources)
        process_module._init_configuration = Mock()
        process_module._init_queues = Mock()
        process_module._init_managers = Mock()
        process_module._init_communication = Mock()
        process_module._register_process_state = Mock()
        process_module._init_system_threads = Mock()
        process_module._init_custom_managers = Mock()
        process_module._init_application_threads = Mock()
        process_module.update_process_state = Mock()
        process_module.communication = Mock()
        process_module.communication.get_queue_stats = Mock(return_value={})
        process_module.worker_manager = Mock()
        process_module.worker_manager.get_stats = Mock(return_value={})
        process_module.initialize()

        stats = process_module.get_stats()
        assert "manager_name" in stats
        assert "is_initialized" in stats

        # 3. WorkerManager
        worker_manager = WorkerManager("TestProcess")
        worker_manager.initialize()

        stats = worker_manager.get_stats()
        assert "manager_name" in stats
        assert "is_initialized" in stats
        assert "workers_count" in stats

    def test_triada_base_manager_inheritance(self):
        """Тест что все три класса наследуются от BaseManager."""
        from multiprocess_framework.modules.base_manager import BaseManager

        # ProcessManagerCore
        mock_shared_resources = Mock()
        mock_queue_registry = Mock()
        mock_config_manager = Mock()
        mock_console_manager = Mock()
        mock_platform = Mock()
        mock_platform.setup_multiprocessing = Mock()

        process_manager = ProcessManagerCore(
            manager_name="TestProcessManager",
            shared_resources=mock_shared_resources,
            queue_registry=mock_queue_registry,
            config_manager=mock_config_manager,
            console_manager=mock_console_manager,
            platform_adapter=mock_platform,
        )

        assert isinstance(process_manager, BaseManager)

        # ProcessModule
        process_module = ProcessModule("TestProcess")
        assert isinstance(process_module, BaseManager)

        # WorkerManager
        worker_manager = WorkerManager("TestProcess")
        assert isinstance(worker_manager, BaseManager)

    def test_triada_observable_mixin(self):
        """Тест что все три класса используют ObservableMixin."""
        from multiprocess_framework.modules.base_manager.mixins.observable_mixin import ObservableMixin

        # ProcessManagerCore
        mock_shared_resources = Mock()
        mock_queue_registry = Mock()
        mock_config_manager = Mock()
        mock_console_manager = Mock()
        mock_platform = Mock()
        mock_platform.setup_multiprocessing = Mock()

        process_manager = ProcessManagerCore(
            manager_name="TestProcessManager",
            shared_resources=mock_shared_resources,
            queue_registry=mock_queue_registry,
            config_manager=mock_config_manager,
            console_manager=mock_console_manager,
            platform_adapter=mock_platform,
        )

        assert isinstance(process_manager, ObservableMixin)
        assert hasattr(process_manager, "log_info")
        assert hasattr(process_manager, "log_error")

        # ProcessModule
        process_module = ProcessModule("TestProcess")
        assert isinstance(process_module, ObservableMixin)
        assert hasattr(process_module, "log_info")
        assert hasattr(process_module, "log_error")

        # WorkerManager
        worker_manager = WorkerManager("TestProcess")
        assert isinstance(worker_manager, ObservableMixin)
        assert hasattr(worker_manager, "log_info")
        assert hasattr(worker_manager, "log_error")
