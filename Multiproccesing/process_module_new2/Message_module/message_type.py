from dataclasses import dataclass, asdict, field
import time
from typing import Dict, List, Any, Optional, Union, Set

from .message_converter import MessageConverter

@dataclass
class BaseMessage(MessageConverter):
    """
    Базовый класс для всех типов сообщений.
    Содержит общие поля и методы для всех сообщений.
    """
    id: str
    type: str
    sender: str
    targets: List[str]
    routers: List[str] = field(default_factory=lambda: ["internal"])
    priority: str = "normal"
    timestamp: float = field(default_factory=time.time)

    def validate(self):
        """
        Валидирует обязательные поля сообщения.

        Raises:
            ValueError: Если обязательные поля не заполнены.
        """
        if not self.targets:
            raise ValueError("Targets cannot be empty")
        if not self.sender:
            raise ValueError("Sender cannot be empty")


# Добавляем класс для обычных сообщений в message_type.py
@dataclass
class GeneralMessage(BaseMessage):
    """
    Класс для создания обычных (общих) сообщений.
    Используется для передачи произвольных данных.
    """
    content: Any = None 

    def validate(self):
        """
        Валидирует обязательные поля обычного сообщения.

        Raises:
            ValueError: Если обязательные поля не заполнены.
        """
        super().validate()
        if self.content is None:
            raise ValueError("Content cannot be None")


# Примеры использования
@dataclass
class CommandMessage(BaseMessage):
    """
    Класс для создания командных сообщений.
    """
    command: str = None
    args: Dict = None
    need_ack: bool = False

    def validate(self):
        """
        Валидирует обязательные поля командного сообщения.

        Raises:
            ValueError: Если обязательные поля не заполнены.
        """
        super().validate()
        if not self.command:
            raise ValueError("Command cannot be empty")

@dataclass
class LogMessage(BaseMessage):
    """
    Класс для создания лог-сообщений.
    """
    level: str = None
    message: str = None
    module: str = "main"

    def validate(self):
        """
        Валидирует обязательные поля лог-сообщения.

        Raises:
            ValueError: Если обязательные поля не заполнены.
        """
        super().validate()
        if not self.level:
            raise ValueError("Level cannot be empty")
        if not self.message:
            raise ValueError("Message cannot be empty")

    def to_dict(self, exclude_none: bool = True, exclude_fields: Set[str] = None, include_fields: Set[str] = None) -> Dict:
        """
        Конвертирует лог-сообщение в словарь, исключая поле 'routers' по умолчанию.

        Args:
            exclude_none (bool): Исключать поля со значением None.
            exclude_fields (Set[str]): Множество имен полей, которые нужно исключить.
            include_fields (Set[str]): Множество имен полей, которые нужно включить.

        Returns:
            Dict: Словарь с данными сообщения.
        """
        # Исключаем поле 'routers' по умолчанию
        if exclude_fields is None:
            exclude_fields = {"routers"}
        else:
            exclude_fields = exclude_fields.union({"routers"})
        return super().to_dict(exclude_none, exclude_fields, include_fields)

@dataclass
class SystemMessage(BaseMessage):
    """
    Класс для создания системных сообщений.
    """
    data: Any = None

    def validate(self):
        """
        Валидирует обязательные поля системного сообщения.

        Raises:
            ValueError: Если обязательные поля не заполнены.
        """
        super().validate()
        if not self.data:
            raise ValueError("Data cannot be empty")