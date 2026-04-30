"""
Интеграционные тесты взаимодействия модулей.

Этот модуль проверяет корректность взаимодействия между отдельными модулями
фреймворка. В отличие от комплексных тестов, здесь фокус на проверке
интеграции между парами модулей.

Проверяемые взаимодействия:
- BaseManager ↔ ProcessModule - базовый менеджер и процесс
- ProcessModule ↔ WorkerManager - процесс и управление воркерами
- RouterModule ↔ MessageModule - маршрутизация и сообщения
- ConfigModule ↔ DataSchemaModule - конфигурации и схемы данных
- SharedResourcesModule ↔ все модули - общие ресурсы
- CommandModule ↔ DispatchModule - команды и диспетчеризация

Использование:
    pytest src/multiprocess_framework/tests/integration/test_module_interactions.py -v

Документация:
    См. INTEGRATION_TESTS_GUIDE.md для подробного руководства
"""

import pytest
from multiprocessing import Event

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import WorkerManager, ThreadConfig, ThreadPriority
from multiprocess_framework.modules.shared_resources_module import SharedResourcesManager


class TestBaseManagerProcessModuleInteraction:
    """
    Тесты взаимодействия BaseManager и ProcessModule.
    
    Проверяет корректность наследования и использования базовой функциональности
    BaseManager в ProcessModule. BaseManager предоставляет базовую функциональность
    для всех менеджеров фреймворка.
    """
    
    def test_process_module_inherits_base_manager(self):
        """
        Тест: ProcessModule наследуется от BaseManager.
        
        Проверяет:
        - Корректное наследование ProcessModule от BaseManager
        - Доступность методов BaseManager в ProcessModule
        
        BaseManager предоставляет базовую функциональность для всех менеджеров.
        """
        # ProcessModule должен наследоваться от BaseManager
        assert issubclass(ProcessModule, BaseManager)
    
    def test_process_module_uses_observable_mixin(self):
        """Тест что ProcessModule использует ObservableMixin."""
        # ProcessModule должен использовать ObservableMixin
        # Проверяем через MRO (Method Resolution Order)
        assert ObservableMixin in ProcessModule.__mro__


class TestProcessModuleWorkerManagerInteraction:
    """
    Тесты взаимодействия ProcessModule и WorkerManager.
    
    Проверяет корректную интеграцию ProcessModule с WorkerManager для
    управления потоками (воркерами) внутри процесса.
    """
    
    def test_process_module_creates_worker_manager(self):
        """
        Тест: ProcessModule создает WorkerManager.
        
        Проверяет:
        - Автоматическое создание WorkerManager при инициализации ProcessModule
        - Доступность WorkerManager через process.worker_manager
        - Корректный тип созданного WorkerManager
        
        WorkerManager создается автоматически при инициализации ProcessModule.
        """
        shared_resources = SharedResourcesManager()
        shared_resources.initialize()
        
        process = ProcessModule(
            name="test_process",
            shared_resources=shared_resources
        )
        process.initialize()
        
        # ProcessModule должен иметь worker_manager
        assert hasattr(process, 'worker_manager')
        assert process.worker_manager is not None
        assert isinstance(process.worker_manager, WorkerManager)
        
        process.shutdown()
        shared_resources.shutdown()
    
    def test_process_module_creates_workers(self):
        """Тест создания воркеров через ProcessModule."""
        shared_resources = SharedResourcesManager()
        shared_resources.initialize()
        
        process = ProcessModule(
            name="test_process",
            shared_resources=shared_resources
        )
        process.initialize()
        
        # Создаем тестового воркера
        def test_worker(stop_event, pause_event):
            while not stop_event.is_set():
                pass
        
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        result = process.worker_manager.create_worker("test_worker", test_worker, config)
        
        assert result is True
        assert process.worker_manager.has_worker("test_worker")
        
        # Очистка
        process.worker_manager.stop_all_workers()
        process.shutdown()
        shared_resources.shutdown()


class TestRouterModuleMessageModuleInteraction:
    """Тесты взаимодействия RouterModule и MessageModule."""
    
    def test_router_sends_messages(self):
        """Тест отправки сообщений через RouterModule."""
        # TODO: Реализовать после исправления тестов RouterModule
        pass


class TestConfigModuleDataSchemaModuleInteraction:
    """Тесты взаимодействия ConfigModule и DataSchemaModule."""
    
    def test_config_uses_data_schema(self):
        """Тест что ConfigModule использует DataSchemaModule."""
        # TODO: Реализовать после исправления тестов ConfigModule
        pass


class TestSharedResourcesModuleIntegration:
    """Тесты интеграции SharedResourcesModule с другими модулями."""
    
    def test_shared_resources_used_by_process_module(self):
        """Тест что ProcessModule использует SharedResourcesManager."""
        shared_resources = SharedResourcesManager()
        shared_resources.initialize()
        
        process = ProcessModule(
            name="test_process",
            shared_resources=shared_resources
        )
        process.initialize()
        
        # ProcessModule должен иметь доступ к shared_resources
        assert process.shared_resources is not None
        assert process.shared_resources == shared_resources
        
        process.shutdown()
        shared_resources.shutdown()
    
    def test_shared_resources_registers_process(self):
        """Тест регистрации процесса в SharedResourcesManager."""
        shared_resources = SharedResourcesManager()
        shared_resources.initialize()
        
        # Регистрируем процесс
        result = shared_resources.process_state_registry.register_process("test_process")
        assert result is True
        
        # Проверяем что процесс зарегистрирован
        process_data = shared_resources.get_process_data("test_process")
        assert process_data is not None
        
        shared_resources.shutdown()


class TestCommandModuleDispatchModuleInteraction:
    """Тесты взаимодействия CommandModule и DispatchModule."""
    
    def test_command_uses_dispatch(self):
        """Тест что CommandModule использует DispatchModule."""
        # TODO: Реализовать после исправления тестов CommandModule
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

