"""
Валидатор сообщений.

Внутренний класс для валидации сообщений перед отправкой.
Используется только внутри модуля Message.
"""

from typing import TYPE_CHECKING
from ..types import MessageType, MESSAGE_TYPE_DEFAULTS, MessageValidationError

if TYPE_CHECKING:
    from ..core.message import Message


class MessageValidator:
    """
    Валидатор сообщений.
    
    Внутренний класс - используется только внутри модуля Message.
    Не предназначен для прямого использования извне.
    """
    
    @staticmethod
    def validate(message: 'Message') -> bool:
        """
        Валидирует сообщение перед отправкой.
        
        Args:
            message: Сообщение для валидации
            
        Returns:
            True если валидно
            
        Raises:
            MessageValidationError: Если сообщение невалидно
        """
        # Базовая валидация
        if not message.sender:
            raise MessageValidationError("Sender cannot be empty")
        
        if not message.targets:
            raise MessageValidationError("Targets cannot be empty")
        
        # Валидация специфичных полей по типу
        try:
            msg_type = MessageType(message.type)
            defaults = MESSAGE_TYPE_DEFAULTS.get(msg_type, {})
            required_fields = defaults.get('required_fields', [])
            
            for field_name in required_fields:
                value = getattr(message, field_name, None)
                if value is None or (isinstance(value, str) and not value):
                    raise MessageValidationError(
                        f"Required field '{field_name}' is empty for message type '{message.type}'"
                    )
        
        except ValueError:
            raise MessageValidationError(f"Unknown message type: {message.type}")
        
        return True
    
    @staticmethod
    def is_valid(message: 'Message') -> bool:
        """
        Проверяет валидность сообщения без выброса исключения.
        
        Args:
            message: Сообщение для проверки
            
        Returns:
            True если валидно, False иначе
        """
        try:
            MessageValidator.validate(message)
            return True
        except MessageValidationError:
            return False

