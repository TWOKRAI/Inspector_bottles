"""
Управление менеджерами процесса.

Отвечает за:
- Создание и инициализацию менеджеров
- Пересоздание менеджеров при изменении конфигурации
- Регистрацию менеджеров и адаптеров
"""

from typing import Dict, Any, Optional

from ..Worker_module.worker_manager import WorkerManager, ThreadConfig, ThreadPriority
from ..Command_module.command_manager import CommandManager
from ..Logger_module.manager import LoggerManager, LogConfig
from ..Router_module.router_manager import RouterManager

from ..Command_module.command_adapter import CommandAdapter
from ..Logger_module.logger_adapter import LoggerAdapter
from ..Router_module.router_adapter import RouterAdapter
# MessageAdapter удален - Message используется напрямую через Message.create() и Message.from_dict()


class ManagersComponents:
    """
    Управление менеджерами процесса.
    
    Инкапсулирует всю логику создания, регистрации и управления менеджерами.
    """
    
    def __init__(
        self,
        process_name: str,
        config_handler,
        shared_resources=None,
        process=None,
        logger_callback=None
    ):
        """
        Инициализация менеджеров процесса.
        
        Args:
            process_name: Имя процесса
            config_handler: ProcessConfigHandler для получения конфигурации
            shared_resources: ProcessInteractionManager
            process: Ссылка на родительский процесс (для адаптеров)
            logger_callback: Функция для логирования ошибок
        """
        self.process_name = process_name
        self.config_handler = config_handler
        self.shared_resources = shared_resources
        self.process = process
        self.logger_callback = logger_callback or (lambda level, msg, ctx: print(f"[{level}] {ctx}: {msg}"))
        
        # Реестр менеджеров
        self.managers: Dict[str, Any] = {}
        
        # Ссылки на основные менеджеры для удобства
        self.worker_manager: Optional[WorkerManager] = None
        self.logger_manager: Optional[LoggerManager] = None
        self.command_manager: Optional[CommandManager] = None
        self.router_manager: Optional[RouterManager] = None
        # MessageManager не нужен - Message используется напрямую через Message.create() и Message.from_dict()
    
    def initialize_core_managers(self):
        """Инициализация основных менеджеров"""
        try:
            managers_config = self.config_handler.get_managers_config()
            
            # Создаем базовые менеджеры
            self.worker_manager = WorkerManager(self.process_name)
            # MessageManager не нужен - Message используется напрямую через Message.create() и Message.from_dict()
            
            # Создаем logger_manager
            self.logger_manager = self._create_logger_manager(managers_config)
            
            # Создаем command_manager
            self.command_manager = self._create_command_manager(managers_config)
            
            # Создаем router_manager
            self.router_manager = self._create_router_manager(managers_config)
            
            # Регистрируем менеджеры
            self.register_manager("worker", self.worker_manager)
            # MessageManager не регистрируется - Message используется напрямую
            self.register_manager("command", self.command_manager)
            self.register_manager("logger", self.logger_manager)
            self.register_manager("router", self.router_manager)
            
            # Создаем и регистрируем адаптеры
            self._create_adapters()
            
            self.logger_callback("INFO", f"Core managers initialized for process '{self.process_name}'", "managers")
            
        except Exception as e:
            self.logger_callback("ERROR", f"Failed to initialize core managers: {e}", "managers")
            raise
    
    def _create_logger_manager(self, managers_config: Dict[str, Any]) -> LoggerManager:
        """Создать logger_manager"""
        log_config = LogConfig()
        log_config.app_name = self.process_name
        
        # Настраиваем logger из конфига
        logger_config = managers_config.get('logger', {})
        if isinstance(logger_config, dict):
            for key, value in logger_config.items():
                if hasattr(log_config, key):
                    setattr(log_config, key, value)
        
        logger_manager = LoggerManager(
            config=log_config,
            process=self.process,  # Ссылка на процесс
            config_manager=self.config_handler.config_manager,
            enable_message_routing=True
        )
        logger_manager.initialize()
        
        return logger_manager
    
    def _create_command_manager(self, managers_config: Dict[str, Any]) -> CommandManager:
        """Создать command_manager"""
        command_config = managers_config.get('command', {})
        
        command_manager = CommandManager(
            self.process_name,
            managers={'logger': self.logger_manager},
            config={'logger': command_config.get('enable_logging', True)},
            config_manager=self.config_handler.config_manager
        )
        
        return command_manager
    
    def _create_router_manager(self, managers_config: Dict[str, Any]) -> RouterManager:
        """Создать router_manager"""
        # Получаем queue_registry из процесса если доступен
        queue_registry = None
        if self.process and hasattr(self.process, 'queue_registry'):
            queue_registry = self.process.queue_registry
        
        router_manager = RouterManager(
            f"router_{self.process_name}", 
            self.logger_manager,
            queue_registry
        )
        
        return router_manager
    
    def _create_adapters(self):
        """Создать адаптеры и подключить их к менеджерам"""
        # Создаем адаптеры
        # MessageAdapter не нужен - Message используется напрямую через Message.create() и Message.from_dict()
        
        if self.command_manager:
            command_adapter = CommandAdapter(self.command_manager, self.process)
            self.command_manager.attach_adapter(command_adapter)
            command_adapter.setup()
        
        if self.logger_manager:
            logger_adapter = LoggerAdapter(self.logger_manager, self.process)
            self.logger_manager.attach_adapter(logger_adapter)
            logger_adapter.setup()
        
        if self.router_manager:
            router_adapter = RouterAdapter(self.router_manager, self.process)
            self.router_manager.attach_adapter(router_adapter)
            router_adapter.setup()
        
        # Для обратной совместимости сохраняем ссылки в self (опционально)
        # Основной доступ теперь через менеджеров
        # MessageAdapter не нужен - Message используется напрямую
        self.command_adapter = self.command_manager.get_adapter() if self.command_manager else None
        self.logger_adapter = self.logger_manager.get_adapter() if self.logger_manager else None
        self.router_adapter = self.router_manager.get_adapter() if self.router_manager else None
    
    def register_manager(self, name: str, manager):
        """Регистрация менеджера"""
        self.managers[name] = manager
    
    def get_manager(self, name: str):
        """Получение менеджера по имени"""
        return self.managers.get(name)
    
    def get_adapter(self, manager_name: str, adapter_name: str = None):
        """
        Получение адаптера через менеджера.
        
        Args:
            manager_name: Имя менеджера
            adapter_name: Имя адаптера (опционально, вернется первый если не указано)
            
        Returns:
            Адаптер или None
        """
        manager = self.get_manager(manager_name)
        if manager and hasattr(manager, 'get_adapter'):
            return manager.get_adapter(adapter_name)
        return None
    
    def reload_manager(self, manager_name: str) -> bool:
        """
        Пересоздать менеджер на основе текущей конфигурации.
        
        Args:
            manager_name: Имя менеджера для пересоздания
            
        Returns:
            bool: True если пересоздание успешно
        """
        try:
            if manager_name not in self.managers:
                self.logger_callback("ERROR", f"Manager '{manager_name}' not found", "reload")
                return False
            
            self.logger_callback("INFO", f"Reloading manager '{manager_name}'", "reload")
            
            # Останавливаем менеджер если есть метод stop
            old_manager = self.managers[manager_name]
            if hasattr(old_manager, 'stop'):
                try:
                    old_manager.stop()
                except Exception as e:
                    self.logger_callback("WARNING", f"Error stopping manager '{manager_name}': {e}", "reload")
            
            # Пересоздаем менеджер
            managers_config = self.config_handler.get_managers_config()
            
            if manager_name == "logger":
                self.logger_manager = self._create_logger_manager(managers_config)
                self.register_manager("logger", self.logger_manager)
                logger_adapter = LoggerAdapter(self.logger_manager, self.process)
                self.logger_manager.attach_adapter(logger_adapter)
                logger_adapter.setup()
                self.logger_adapter = logger_adapter
                
            elif manager_name == "command":
                self.command_manager = self._create_command_manager(managers_config)
                self.register_manager("command", self.command_manager)
                command_adapter = CommandAdapter(self.command_manager, self.process)
                self.command_manager.attach_adapter(command_adapter)
                command_adapter.setup()
                self.command_adapter = command_adapter
                
            elif manager_name == "router":
                self.router_manager = self._create_router_manager(managers_config)
                self.register_manager("router", self.router_manager)
                router_adapter = RouterAdapter(self.router_manager, self.process)
                self.router_manager.attach_adapter(router_adapter)
                router_adapter.setup()
                self.router_adapter = router_adapter
                
            else:
                self.logger_callback("WARNING", f"Auto-reload not supported for '{manager_name}'", "reload")
                return False
            
            self.logger_callback("INFO", f"Manager '{manager_name}' reloaded successfully", "reload")
            return True
            
        except Exception as e:
            self.logger_callback("ERROR", f"Failed to reload manager '{manager_name}': {e}", "reload")
            return False
    
    def stop_all(self):
        """Остановка всех менеджеров и их адаптеров"""
        # Останавливаем менеджеры (адаптеры хранятся внутри менеджеров)
        for name, manager in self.managers.items():
            # Останавливаем адаптеры менеджера
            if hasattr(manager, 'list_adapters'):
                for adapter_name in manager.list_adapters():
                    adapter = manager.get_adapter(adapter_name)
                    if adapter and hasattr(adapter, 'stop'):
                        try:
                            adapter.stop()
                        except Exception as e:
                            self.logger_callback("WARNING", f"Error stopping adapter '{adapter_name}' of manager '{name}': {e}", "stop")
            
            # Останавливаем сам менеджер
            if hasattr(manager, 'stop'):
                try:
                    manager.stop()
                except Exception as e:
                    self.logger_callback("WARNING", f"Error stopping manager '{name}': {e}", "stop")
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики менеджеров (адаптеры включены в статистику менеджеров)"""
        stats = {
            "managers": {}
        }
        
        # Статистика менеджеров (включает информацию об адаптерах)
        for name, manager in self.managers.items():
            if hasattr(manager, 'get_stats'):
                try:
                    stats["managers"][name] = manager.get_stats()
                except Exception as e:
                    stats["managers"][name] = {"error": str(e)}
        
        return stats

