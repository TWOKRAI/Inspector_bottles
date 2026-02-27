"""
Диспетчер для маршрутизации логов по каналам.
Использует новый Dispatcher из dispatch_module.
"""
import time
from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass

from ...dispatch_module import Dispatcher, DispatchStrategy
from .log_config import LogLevel, LogScope


@dataclass
class LogRecord:
    """Запись лога"""
    timestamp: float
    level: LogLevel
    scope: LogScope
    message: str
    module: str
    extra: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует запись в словарь"""
        return {
            'timestamp': self.timestamp,
            'level': self.level.value,
            'scope': self.scope.value,
            'message': self.message,
            'module': self.module,
            'extra': self.extra
        }


class LogDispatcher:
    """
    Специализированный диспетчер для логирования.
    Маршрутизирует логи по каналам на основе конфигурации.
    
    Использует Dispatcher из dispatch_module для маршрутизации.
    """
    
    def __init__(self, app_name: str, process: Optional[Any] = None):
        """
        Инициализация диспетчера логов.
        
        Args:
            app_name: Имя приложения
            process: Ссылка на родительский процесс (опционально)
        """
        self.app_name = app_name
        self.dispatcher = Dispatcher(
            manager_name=f"{app_name}_logger_dispatcher",
            process=process,
            default_strategy=DispatchStrategy.EXACT_MATCH
        )
        self.channel_handlers: Dict[str, Callable] = {}
    
    def initialize(self) -> bool:
        """Инициализация диспетчера."""
        return self.dispatcher.initialize()
    
    def shutdown(self) -> bool:
        """Завершение работы диспетчера."""
        return self.dispatcher.shutdown()
    
    def register_channel_handler(self, channel_name: str, handler: Callable):
        """
        Регистрирует обработчик для канала.
        
        Args:
            channel_name: Имя канала
            handler: Функция обработки записи лога
        """
        self.channel_handlers[channel_name] = handler
        
        # Регистрируем в диспетчере
        self.dispatcher.register_handler(
            key=channel_name,
            handler=handler,
            metadata={'channel': channel_name}
        )
    
    def route_log(self, record: LogRecord, channel_names: List[str]) -> Dict[str, Any]:
        """
        Маршрутизирует запись лога в указанные каналы.
        
        Args:
            record: Запись лога
            channel_names: Список каналов для записи
            
        Returns:
            Словарь с результатами записи для каждого канала
        """
        results = {}
        record_dict = record.to_dict()
        
        for channel_name in channel_names:
            if channel_name in self.channel_handlers:
                try:
                    # Используем диспетчер для маршрутизации
                    result = self.dispatcher.dispatch(channel_name, record_dict)
                    results[channel_name] = result
                except Exception as e:
                    results[channel_name] = {
                        'status': 'error',
                        'error': str(e)
                    }
            else:
                results[channel_name] = {
                    'status': 'error', 
                    'error': f'Channel {channel_name} not found'
                }
        
        return results

