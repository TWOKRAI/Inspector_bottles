"""
Командный менеджер для обработки и управления командами.

Простая абстракция над диспетчером, упрощающая работу с командами.
Наследуется от BaseManager и использует ObservableMixin для единообразия со всеми менеджерами системы.
"""
from typing import Dict, Any, Callable, Optional, List, TYPE_CHECKING
import time

if TYPE_CHECKING:
    from multiprocessing import Process

from ...dispatch_module import Dispatcher, DispatchStrategy
from ...base_manager import BaseManager, ObservableMixin


class CommandManager(BaseManager, ObservableMixin):
    """
    Командный менеджер для обработки и управления командами.

    Наследуется от BaseManager и использует ObservableMixin для:
    - Единообразия со всеми менеджерами системы
    - Автоматического логирования через ObservableMixin
    - Стандартного жизненного цикла (initialize/shutdown)

    Этот класс предоставляет простой интерфейс для регистрации и обработки команд,
    используя универсальный диспетчер для управления обработчиками.

    Attributes:
        manager_name (str): Имя менеджера (синоним process_name для совместимости)
        process_name (str): Имя процесса для идентификации (для обратной совместимости)
        dispatcher (Dispatcher): Внутренний диспетчер для управления обработчиками команд
    
    Пример использования:
        manager = CommandManager(
            manager_name="my_process",
            managers={'logger': logger_manager, 'statistics': stats_manager}
        )
        manager.initialize()
        
        manager.register_command("greet", greet_handler)
        result = manager.handle_command({"command": "greet", "data": {"name": "Alice"}})
        
        manager.shutdown()
    """

    def __init__(
        self,
        manager_name: str,
        process: Optional["Process"] = None,
        default_strategy: DispatchStrategy = DispatchStrategy.EXACT_MATCH,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        config_manager: Optional[Any] = None,
        # Обратная совместимость со старым API
        logger_manager: Optional[Any] = None,
        error_manager: Optional[Any] = None,
        statistics_manager: Optional[Any] = None,
        enable_logging: bool = True,
        enable_error_tracking: bool = True,
        enable_statistics: bool = True,
        **kwargs
    ):
        """
        Инициализация командного менеджера.

        Args:
            manager_name (str): Имя менеджера (для BaseManager)
            process (Process): Ссылка на родительский процесс (опционально, для BaseManager)
            default_strategy (DispatchStrategy): Стратегия диспетчера по умолчанию
            managers: Словарь менеджеров {имя: менеджер} (новый универсальный способ)
            config: Конфигурация включения/выключения функций {имя: bool}
            config_manager: Менеджер конфигурации для динамического обновления
            logger_manager: Менеджер логирования (для обратной совместимости)
            error_manager: Менеджер обработки ошибок (для обратной совместимости)
            statistics_manager: Менеджер статистики (для обратной совместимости)
            enable_logging: Включить логирование по умолчанию (для обратной совместимости)
            enable_error_tracking: Включить отслеживание ошибок по умолчанию
            enable_statistics: Включить статистику по умолчанию
            **kwargs: Дополнительные параметры для BaseManager и ObservableMixin
        """
        # Инициализация BaseManager
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        
        # Для обратной совместимости
        self.process_name = manager_name
        
        # Поддержка старого API для обратной совместимости
        if managers is None:
            managers = {}
            if logger_manager:
                managers['logger'] = logger_manager
            if error_manager:
                managers['error'] = error_manager
            if statistics_manager:
                managers['statistics'] = statistics_manager
        
        if config is None:
            config = {
                'logger': enable_logging,
                'error': enable_error_tracking,
                'statistics': enable_statistics
            }
        
        # Инициализация ObservableMixin
        ObservableMixin.__init__(
            self,
            managers=managers,
            config=config
        )
        
        self.dispatcher = Dispatcher(
            manager_name=f"{manager_name}_commands",
            process=process,
            default_strategy=default_strategy,
            managers=managers,
            config=config,
        )
        
        # НЕ вызываем initialize() здесь - это делается явно после создания

    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseManager - ЖИЗНЕННЫЙ ЦИКЛ
    # ========================================================================
    
    def initialize(self) -> bool:
        """
        Инициализация командного менеджера.
        
        Инициализирует внутренний диспетчер и готовит менеджер к работе.
        
        Returns:
            bool: True если инициализация успешна
        """
        try:
            # Инициализация диспетчера
            if not self.dispatcher.initialize():
                return False
            
            self.is_initialized = True
            self._log_info(f"CommandManager '{self.manager_name}' initialized")
            self._record_metric("command_manager.initialization.success", tags={"name": self.manager_name})
            return True
        except Exception as e:
            self._log_error(f"Failed to initialize CommandManager: {e}")
            self._track_error("command_manager.initialization.failed", error=e)
            return False
    
    def shutdown(self) -> bool:
        """
        Завершение работы командного менеджера.
        
        Завершает внутренний диспетчер и освобождает ресурсы.
        
        Returns:
            bool: True если завершение успешно
        """
        try:
            # Завершение диспетчера
            if self.dispatcher:
                self.dispatcher.shutdown()
            
            self.is_initialized = False
            self._log_info(f"CommandManager '{self.manager_name}' shutdown completed")
            self._record_metric("command_manager.shutdown.success", tags={"name": self.manager_name})
            return True
        except Exception as e:
            self._log_error(f"Error during CommandManager shutdown: {e}")
            self._track_error("command_manager.shutdown.failed", error=e)
            return False

    # ========================================================================
    # РЕАЛИЗАЦИЯ BaseCommandManager - РАБОТА С КОМАНДАМИ
    # ========================================================================

    def register_command(
        self,
        command_name: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None,
        strategy: Optional[DispatchStrategy] = None,
        **kwargs
    ) -> bool:
        """
        Регистрация новой команды.

        Args:
            command_name (str): Название команды (ключ для диспетчеризации)
            handler (Callable): Функция-обработчик команды
            expects_full_message (bool): Если True, обработчик получает всё сообщение
            metadata (Dict): Дополнительные метаданные команды
            efficiency (int): Уровень эффективности (для FALLBACK_MATCH)
            tags (List[str]): Список тегов для группировки
            strategy (DispatchStrategy): Стратегия для регистрации (опционально)
            **kwargs: Дополнительные аргументы для регистрации обработчика

        Returns:
            bool: Успешность регистрации

        Example:
            def greet_handler(data):
                return f"Hello, {data.get('name', 'World')}!"

            manager.register_command("greet", greet_handler)
        """
        self._log_debug(f"Registering command: {command_name}", module="command_manager")
        self._record_metric("command_manager.command.registration.attempts", tags={"command": command_name})
        
        result = self.dispatcher.register_handler(
            key=command_name,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata,
            efficiency=efficiency,
            tags=tags,
            strategy=strategy
        )
        
        if result:
            self._log_info(f"Command '{command_name}' registered successfully", module="command_manager")
            self._record_metric("command_manager.command.registration.success", tags={"command": command_name})
        else:
            self._log_warning(f"Failed to register command '{command_name}'", module="command_manager")
            self._record_metric("command_manager.command.registration.failed", tags={"command": command_name})
        
        return result

    def handle_command(self, message: Dict) -> Any:
        """
        Обработка командного сообщения.

        Args:
            message (Dict): Сообщение для обработки. Ожидается поле 'command' с именем команды.

        Returns:
            Any: Результат выполнения команды или сообщение об ошибке

        Example:
            message = {
                "command": "greet",
                "data": {"name": "Alice"}
            }
            result = manager.handle_command(message)
        """
        start_time = time.time()
        command_name = message.get("command", "unknown")
        
        self._log_debug(f"Handling command: {command_name}", module="command_manager", command=command_name)
        self._record_metric("command_manager.command.execution.attempts", tags={"command": command_name})
        
        try:
            result = self.dispatcher.dispatch(message, key_field="command", data_field="data")
            
            duration = time.time() - start_time
            if isinstance(result, dict) and result.get("status") == "error":
                self._log_warning(f"Command '{command_name}' failed: {result.get('reason')}", module="command_manager")
                self._record_metric("command_manager.command.execution.errors", tags={"command": command_name})
            else:
                self._log_info(f"Command '{command_name}' executed successfully in {duration:.3f}s", module="command_manager")
                self._record_metric("command_manager.command.execution.success", tags={"command": command_name})
            
            self._record_timing("command_manager.command.execution.duration", duration, tags={"command": command_name})
            return result
        except Exception as e:
            duration = time.time() - start_time
            self._log_error(f"Command '{command_name}' execution failed: {str(e)}", module="command_manager")
            self._track_error(e, {"command": command_name, "message": str(message)})
            self._record_timing("command_manager.command.execution.error_duration", duration)
            self._record_metric("command_manager.command.execution.errors", tags={"command": command_name})
            raise

    def get_commands(self) -> List[Dict]:
        """
        Получение списка всех зарегистрированных команд.

        Returns:
            List[Dict]: Список словарей с информацией о каждом обработчике

        Example:
            commands = manager.get_commands()
            for cmd in commands:
                print(f"Command: {cmd['key']}")
        """
        return self.dispatcher.get_all_handlers()
    
    # ========================================================================
    # ДОПОЛНИТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Получение статистики командного менеджера.
        
        Returns:
            Dict[str, Any]: Статистика менеджера
        """
        commands = self.get_commands()
        base_stats = super().get_stats()  # Получаем статистику от BaseManager
        
        return {
            **base_stats,
            "process_name": self.process_name,  # Для обратной совместимости
            "total_commands": len(commands),
            "commands": [cmd.get('key', '') for cmd in commands],
            "dispatcher_strategy": self.dispatcher.default_strategy.value
        }
    
    def get_command_info(self, command_name: str) -> Optional[Dict]:
        """
        Получение информации о конкретной команде.
        
        Args:
            command_name: Название команды
            
        Returns:
            Словарь с информацией о команде или None
        """
        return self.dispatcher.get_handler_info(command_name)
    
    def get_commands_by_tag(self, tag: str) -> List[Dict]:
        """
        Получение команд по тегу.
        
        Args:
            tag: Тег для фильтрации
            
        Returns:
            Список команд с указанным тегом
        """
        return self.dispatcher.get_handlers_by_tag(tag)
    
    def update_command_metadata(self, command_name: str, metadata: Dict[str, Any]) -> bool:
        """
        Обновление метаданных команды.
        
        Args:
            command_name: Название команды
            metadata: Новые метаданные
            
        Returns:
            True если обновлено, False в случае ошибки
        """
        return self.dispatcher.update_handler_metadata(command_name, metadata)
    
    def update_command_tags(self, command_name: str, tags: List[str]) -> bool:
        """
        Обновление тегов команды.
        
        Args:
            command_name: Название команды
            tags: Новые теги
            
        Returns:
            True если обновлено, False в случае ошибки
        """
        return self.dispatcher.update_handler_tags(command_name, tags)
    
    def overwrite_command(
        self,
        command_name: str,
        handler: Callable,
        expects_full_message: bool = False,
        metadata: Dict[str, Any] = None,
        efficiency: int = 0,
        tags: List[str] = None
    ) -> bool:
        """
        Принудительная перезапись команды.
        
        Args:
            command_name: Название команды
            handler: Новый обработчик
            expects_full_message: Если True, обработчик получает всё сообщение
            metadata: Метаданные команды
            efficiency: Уровень эффективности
            tags: Список тегов
            
        Returns:
            True если перезаписано, False в случае ошибки
        """
        return self.dispatcher.overwrite_handler(
            key=command_name,
            handler=handler,
            expects_full_message=expects_full_message,
            metadata=metadata,
            efficiency=efficiency,
            tags=tags
        )

