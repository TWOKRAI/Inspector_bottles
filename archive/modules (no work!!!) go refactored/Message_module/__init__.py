"""
Message Module - Универсальная система сообщений.

Этот модуль предоставляет единый класс Message для работы со всеми типами сообщений
в системе межпроцессного взаимодействия.

Основные компоненты:
    - Message: Универсальный класс сообщений
    - MessageType: Enum с типами сообщений
    - Priority: Enum с приоритетами
    - LogLevel: Enum с уровнями логирования
    - MessageValidationError: Исключение для ошибок валидации

Быстрый старт:
    from ..Message_module import Message, MessageType
    
    # Создание сообщения
    msg = Message.create(
        type=MessageType.COMMAND,
        sender="GUI",
        targets=["Worker"],
        command="process",
        args={"id": 123}
    )
    
    # Отправка через роутер
    router.send(msg)
"""

from .message import (
    Message,
    MessageValidationError,
    create_message,
    parse_message
)

from .message_types import (
    MessageType,
    Priority,
    LogLevel,
    MessageSchema,
    MESSAGE_TYPE_DEFAULTS,
    MESSAGE_TYPE_EXCLUDE_FIELDS
)

__all__ = [
    # Основной класс
    'Message',
    
    # Исключения
    'MessageValidationError',
    
    # Вспомогательные функции
    'create_message',
    'parse_message',
    
    # Типы и енумы
    'MessageType',
    'Priority',
    'LogLevel',
    'MessageSchema',
    
    # Конфигурация
    'MESSAGE_TYPE_DEFAULTS',
    'MESSAGE_TYPE_EXCLUDE_FIELDS',
]

__version__ = '2.0.0'
