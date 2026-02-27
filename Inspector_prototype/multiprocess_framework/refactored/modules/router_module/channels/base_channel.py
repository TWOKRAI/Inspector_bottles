"""
Базовый интерфейс для каналов сообщений (Refactored).

Универсальная система каналов для отправки и приема сообщений.

Философия:
- Каждый канал может как отправлять, так и принимать сообщения
- Единый интерфейс для всех типов каналов
- Легко расширяемая архитектура
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Callable

from ..interfaces import IMessageChannel


class MessageChannel(IMessageChannel):
    """
    Базовый класс для всех каналов сообщений.
    
    Определяет единый интерфейс для всех типов каналов (Queue, Logger, HTTP, etc.).
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Уникальное имя канала."""
        pass
    
    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Тип канала (queue, log, telegram, http, etc)."""
        pass
    
    @abstractmethod
    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Отправить сообщение через канал.
        
        Args:
            message: Сообщение для отправки
            
        Returns:
            Результат отправки
        """
        pass
    
    @abstractmethod
    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """
        Опрос канала для получения сообщений.
        
        Args:
            timeout: Таймаут опроса (0 = non-blocking)
            
        Returns:
            Список полученных сообщений
        """
        pass
    
    def start_listening(self, callback: Callable[[Dict[str, Any]], None]) -> bool:
        """
        Запуск асинхронного прослушивания канала.
        
        Args:
            callback: Функция обратного вызова для полученных сообщений
            
        Returns:
            True если запущено успешно
        """
        # По умолчанию не поддерживается
        return False
    
    def stop_listening(self) -> bool:
        """Остановить прослушивание канала."""
        return True
    
    def get_info(self) -> Dict[str, Any]:
        """Получить информацию о канале."""
        return {
            "name": self.name,
            "type": self.channel_type,
            "active": True
        }

