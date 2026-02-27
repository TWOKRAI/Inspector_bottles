"""
Интерфейсы для Message Module.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .types import MessageType
    from .core.message import Message


class IMessageFactory(ABC):
    """Интерфейс для фабрики сообщений."""
    
    @abstractmethod
    def create(
        self,
        msg_type: Union[str, 'MessageType'],
        sender: str,
        **kwargs
    ) -> 'Message':
        """
        Создать сообщение.
        
        Args:
            msg_type: Тип сообщения
            sender: Отправитель
            **kwargs: Дополнительные параметры
            
        Returns:
            Экземпляр сообщения
        """
        pass


class IMessageValidator(ABC):
    """Интерфейс для валидатора сообщений."""
    
    @abstractmethod
    def validate(self, message: 'Message') -> bool:
        """
        Валидировать сообщение.
        
        Args:
            message: Сообщение для валидации
            
        Returns:
            True если сообщение валидно
            
        Raises:
            MessageValidationError: Если сообщение невалидно
        """
        pass


class IMessageConverter(ABC):
    """Интерфейс для конвертера сообщений."""
    
    @abstractmethod
    def to_dict(self, message: 'Message') -> Dict[str, Any]:
        """Конвертировать сообщение в словарь."""
        pass
    
    @abstractmethod
    def to_json(self, message: 'Message') -> str:
        """Конвертировать сообщение в JSON."""
        pass
    
    @abstractmethod
    def from_dict(self, data: Dict[str, Any]) -> 'Message':
        """Создать сообщение из словаря."""
        pass
    
    @abstractmethod
    def from_json(self, json_str: str) -> 'Message':
        """Создать сообщение из JSON."""
        pass

