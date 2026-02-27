"""
ProcessManagerProcess - процесс системы для управления процессами (Refactored).

Наследуется от ProcessModule и использует ProcessManagerCore для управления процессами.
Является Сверхэго в архитектуре "Тройцы создания циклов".
"""

from typing import Dict, Any, Optional

from ...process_module import ProcessModule
from ..core.process_manager_core import ProcessManagerCore
from ..monitor import ProcessMonitor


class ProcessManagerProcess(ProcessModule):
    """
    ProcessManagerProcess - процесс системы для управления процессами (Refactored).
    
    Наследуется от ProcessModule (Эго) и использует ProcessManagerCore (Сверхэго)
    для управления всеми процессами системы.
    
    Является Сверхэго в архитектуре "Тройцы создания циклов":
    - ProcessManagerProcess (Сверхэго) - управляет всеми процессами системы
    - ProcessModule (Эго) - базовый процесс, выполняет работу
    - WorkerManager (Ид) - управляет потоками внутри процесса
    
    Attributes:
        core: ProcessManagerCore для управления процессами
    """
    
    def __init__(
        self,
        name: str = "ProcessManager",
        shared_resources=None,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        Инициализация ProcessManagerProcess.
        
        Args:
            name: Имя процесса (по умолчанию "ProcessManager")
            shared_resources: Менеджер общих ресурсов
            config: Конфигурация процесса
        """
        # Инициализируем ProcessModule (Эго)
        super().__init__(name, shared_resources, config)
        
        # Создаем ProcessManagerCore (Сверхэго)
        # Импортируем зависимости (временно из старого модуля)
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent / "modules"))
        
        from Config_module.config_manager import ConfigManager
        from Shared_resources_module.queue_registry import QueueRegistry
        from Console_module import ConsoleManager
        from Process_manager_module.platforms import get_platform_adapter
        
        # Создаем локальные менеджеры
        config_manager = ConfigManager()
        queue_registry = QueueRegistry(
            process_state_registry=self.shared_resources.process_state_registry if self.shared_resources else None
        )
        console_manager = ConsoleManager(logger=self.logger_manager if hasattr(self, 'logger_manager') else None)
        platform_adapter = get_platform_adapter()
        
        # Создаем ProcessManagerCore
        self.core = ProcessManagerCore(
            manager_name=name,
            shared_resources=shared_resources,
            queue_registry=queue_registry,
            config_manager=config_manager,
            console_manager=console_manager,
            logger=self.logger_manager if hasattr(self, 'logger_manager') else None,
            platform_adapter=platform_adapter,
            stop_event=self.stop_event if hasattr(self, 'stop_event') else None,
            process=self
        )
        
        # Регистрируем core как менеджер через ObservableMixin
        self.register_manager('process_manager', self.core, enabled=True)
        
        # Создаем ProcessMonitor для мониторинга состояний процессов
        self.process_monitor = ProcessMonitor(self, poll_interval=0.5)
    
    def initialize(self) -> bool:
        """
        Инициализация ProcessManagerProcess.
        
        Returns:
            bool: True если инициализация успешна
        """
        # Инициализация ProcessModule (Эго)
        if not super().initialize():
            return False
        
        # Инициализация ProcessManagerCore (Сверхэго)
        if not self.core.initialize():
            return False
        
        # Запускаем мониторинг состояний процессов
        self.process_monitor.start()
        
        return True
    
    def shutdown(self) -> bool:
        """
        Завершение работы ProcessManagerProcess.
        
        Returns:
            bool: True если завершение успешно
        """
        # Останавливаем мониторинг состояний процессов
        if hasattr(self, 'process_monitor'):
            self.process_monitor.stop()
        
        # Завершение ProcessManagerCore (Сверхэго)
        if self.core:
            self.core.shutdown()
        
        # Завершение ProcessModule (Эго)
        return super().shutdown()
    
    # Делегирование методов к ProcessManagerCore
    def create_process(self, name: str, class_path: str, config: Optional[Dict[str, Any]] = None, priority: str = "normal"):
        """Создание процесса через ProcessManagerCore."""
        return self.core.create_process(name, class_path, config, priority)
    
    def start_process(self, process_name: Optional[str] = None) -> bool:
        """Запуск процесса через ProcessManagerCore."""
        return self.core.start_process(process_name)
    
    def stop_process(self, process_name: Optional[str] = None) -> bool:
        """Остановка процесса через ProcessManagerCore."""
        return self.core.stop_process(process_name)
    
    def get_process_status(self, process_name: str):
        """Получение статуса процесса через ProcessManagerCore."""
        return self.core.get_process_status(process_name)
    
    def get_all_processes_status(self):
        """Получение статусов всех процессов через ProcessManagerCore."""
        return self.core.get_all_processes_status()

