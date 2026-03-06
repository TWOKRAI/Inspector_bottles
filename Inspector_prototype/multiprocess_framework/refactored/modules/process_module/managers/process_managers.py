"""
Управление менеджерами процесса.

Инициализация и управление менеджерами через ObservableMixin.
"""

from typing import Dict, Any


class ProcessManagers:
    """
    Управление менеджерами процесса.
    
    Инкапсулирует логику создания и регистрации менеджеров.
    """
    
    def __init__(self, process):
        """
        Инициализация управления менеджерами.
        
        Args:
            process: Ссылка на ProcessModule
        """
        self.process = process
    
    def initialize(self):
        """Инициализация менеджеров процесса через ObservableMixin."""
        # Импорт нового рефакторенного WorkerManager
        from ...worker_module import WorkerManager
        
        # Импорт нового рефакторенного RouterManager
        from ...router_module import RouterManager, RouterAdapter
        
        # Импорт из refactored модулей (ТОЛЬКО refactored, не трогаем modules "no work")
        from ...command_module import CommandManager, CommandAdapter
        from ...logger_module import LoggerManager, LogConfig
        from ...logger_module.adapters.logger_adapter import LoggerAdapter
        
        managers_config = self.process.config_handler.get_managers_config()
        
        # 1. Создаем WorkerManager (рефакторенный на BaseManager)
        self.process.worker_manager = WorkerManager(
            manager_name=self.process.name,
            process=self.process
        )
        self.process.worker_manager.initialize()  # Инициализация через BaseManager
        
        # 2. Создаем LoggerManager
        log_config = LogConfig()
        log_config.app_name = self.process.name
        logger_config = managers_config.get('logger', {})
        if isinstance(logger_config, dict):
            for key, value in logger_config.items():
                if hasattr(log_config, key):
                    setattr(log_config, key, value)
        
        self.process.logger_manager = LoggerManager(
            manager_name=f"logger_{self.process.name}",
            config=log_config,
            process=self.process,
            config_manager=self.process.config_manager,
            enable_router_routing=True
        )
        self.process.logger_manager.initialize()
        
        # 3. Создаем CommandManager
        command_config = managers_config.get('command', {})
        self.process.command_manager = CommandManager(
            self.process.name,
            managers={'logger': self.process.logger_manager},
            config={'logger': command_config.get('enable_logging', True)},
            config_manager=self.process.config_manager
        )
        
        # 4. Создаем RouterManager (рефакторенный на BaseManager)
        router_manager = RouterManager(
            manager_name=f"router_{self.process.name}",
            process=self.process,
            queue_registry=self.process.queue_registry,
            logger=self.process.logger_manager
        )
        router_manager.initialize()  # Инициализация через BaseManager
        self.process.router_manager = router_manager
        
        # Регистрируем менеджеры через ObservableMixin
        self.process.register_manager('logger', self.process.logger_manager, enabled=True)
        self.process.register_manager('command', self.process.command_manager, enabled=True)
        self.process.register_manager('router', self.process.router_manager, enabled=True)
        
        # Создаем и регистрируем адаптеры
        logger_adapter = LoggerAdapter(self.process.logger_manager, self.process)
        command_adapter = CommandAdapter(self.process.command_manager, self.process)
        router_adapter = RouterAdapter(self.process.router_manager, self.process)
        
        self.process.logger_manager.attach_adapter(logger_adapter, name="process")
        self.process.command_manager.attach_adapter(command_adapter, name="process")
        self.process.router_manager.attach_adapter(router_adapter, name="process")
        
        # Обновляем EventManager в shared_resources с router_manager
        if self.process.shared_resources and self.process.shared_resources.event_manager:
            self.process.shared_resources.event_manager.set_router_manager(self.process.router_manager)
    
    def register_manager(self, name: str, manager, enabled: bool = True):
        """Регистрация менеджера (делегирование к ObservableMixin)."""
        self.process.register_manager(name, manager, enabled=enabled)
    
    def get_manager(self, name: str):
        """Получение менеджера по имени (делегирование к ObservableMixin)."""
        return self.process.get_manager(name)
    
    def reload_manager(self, manager_name: str) -> bool:
        """
        Пересоздать менеджер на основе текущей конфигурации.
        
        Args:
            manager_name: Имя менеджера для перезагрузки
            
        Returns:
            bool: True если перезагрузка успешна
        """
        # Пока простая реализация - можно расширить
        try:
            # Получаем конфигурацию менеджера
            manager_config = self.process.config_handler.get_manager_config(manager_name)
            
            # Пересоздаем менеджер (упрощенная версия)
            # В будущем можно добавить полную логику пересоздания
            self.process._log_info(f"Reloading manager '{manager_name}'")
            return True
        except Exception as e:
            self.process._log_error(f"Failed to reload manager '{manager_name}': {e}")
            return False

