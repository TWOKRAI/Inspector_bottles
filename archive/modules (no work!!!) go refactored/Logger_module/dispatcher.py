"""
Диспетчер для маршрутизации логов по каналам.
Использует стратегии из твоего DispatchHandler.
"""

import time
from typing import Dict, List, Any, Callable, Optional
from dataclasses import dataclass

from ..Dispatch_module import Dispatcher, DispatchStrategy
from ..Logger_module.config import LogLevel, LogScope, ChannelConfig

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

class LogDispatcher(Dispatcher):
    """
    Специализированный диспетчер для логирования.
    Маршрутизирует логи по каналам на основе конфигурации.
    """
    
    def __init__(self, app_name: str):
        super().__init__(f"{app_name}_logger", DispatchStrategy.EXACT_MATCH)
        self.app_name = app_name
        self.channel_handlers: Dict[str, Callable] = {}
    
    def register_channel_handler(self, channel_name: str, handler: Callable):
        """Регистрирует обработчик для канала"""
        self.channel_handlers[channel_name] = handler
        
        # Регистрируем в диспетчере
        self.register_handler(
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
        
        for channel_name in channel_names:
            if channel_name in self.channel_handlers:
                try:
                    result = self.channel_handlers[channel_name](record.to_dict())
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