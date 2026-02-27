"""
Конвертер сообщений.

Внутренний класс для конвертации сообщений в различные форматы.
Используется только внутри модуля Message.
"""

import json
from typing import Dict, Any, Optional, Set, TYPE_CHECKING

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from ..types import MessageType, MESSAGE_TYPE_EXCLUDE_FIELDS

if TYPE_CHECKING:
    from ..core.message import Message


class MessageConverter:
    """
    Конвертер сообщений.
    
    Внутренний класс - используется только внутри модуля Message.
    Не предназначен для прямого использования извне.
    """
    
    @staticmethod
    def to_dict(
        message: 'Message',
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """
        Конвертирует сообщение в словарь.
        
        Args:
            message: Сообщение для конвертации
            exclude_none: Исключать поля со значением None
            exclude_fields: Множество полей для исключения
            include_fields: Множество полей для включения
            
        Returns:
            Словарь с данными сообщения
        """
        # Ленивая синхронизация
        message._sync_to_dict()
        
        data = message._data.copy()
        
        # Применяем exclude_fields для типа сообщения
        try:
            msg_type = MessageType(message.type)
            type_exclude = MESSAGE_TYPE_EXCLUDE_FIELDS.get(msg_type, set())
            if exclude_fields:
                exclude_fields = exclude_fields.union(type_exclude)
            else:
                exclude_fields = type_exclude
        except ValueError:
            pass
        
        # Исключаем None
        if exclude_none:
            data = {k: v for k, v in data.items() if v is not None}
        
        # Исключаем пустые списки и словари
        data = {
            k: v for k, v in data.items()
            if not (isinstance(v, (list, dict)) and not v)
        }
        
        # Применяем exclude_fields
        if exclude_fields:
            data = {k: v for k, v in data.items() if k not in exclude_fields}
        
        # Применяем include_fields
        if include_fields:
            data = {k: v for k, v in data.items() if k in include_fields}
        
        return data
    
    @staticmethod
    def to_json(
        message: 'Message',
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
        indent: Optional[int] = None
    ) -> str:
        """
        Конвертирует сообщение в JSON строку.
        
        Args:
            message: Сообщение для конвертации
            exclude_none: Исключать поля со значением None
            exclude_fields: Множество полей для исключения
            include_fields: Множество полей для включения
            indent: Отступ для форматирования
            
        Returns:
            JSON строка
        """
        data = MessageConverter.to_dict(message, exclude_none, exclude_fields, include_fields)
        return json.dumps(data, indent=indent, ensure_ascii=False)
    
    @staticmethod
    def to_yaml(
        message: 'Message',
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None
    ) -> str:
        """
        Конвертирует сообщение в YAML строку.
        
        Args:
            message: Сообщение для конвертации
            exclude_none: Исключать поля со значением None
            exclude_fields: Множество полей для исключения
            include_fields: Множество полей для включения
            
        Returns:
            YAML строка
            
        Raises:
            ImportError: Если PyYAML не установлен
        """
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML is not installed. Install it with: pip install pyyaml")
        
        data = MessageConverter.to_dict(message, exclude_none, exclude_fields, include_fields)
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)
    
    @staticmethod
    def to_text(
        message: 'Message',
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None
    ) -> str:
        """
        Конвертирует сообщение в текстовый формат.
        
        Args:
            message: Сообщение для конвертации
            exclude_none: Исключать поля со значением None
            exclude_fields: Множество полей для исключения
            include_fields: Множество полей для включения
            
        Returns:
            Текстовое представление
        """
        data = MessageConverter.to_dict(message, exclude_none, exclude_fields, include_fields)
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"{key}: {value}")
        return "\n".join(lines)
    
    @staticmethod
    def from_dict(data: Dict[str, Any], message_class: type) -> 'Message':
        """
        Создает сообщение из словаря.
        
        Использует фабричный метод create() если доступен, иначе конструктор.
        Не нарушает инкапсуляцию - не обращается к protected полям напрямую.
        
        Args:
            data: Словарь с данными сообщения
            message_class: Класс сообщения
            
        Returns:
            Экземпляр сообщения
        """
        # Используем фабричный метод если доступен (для Message.create)
        if hasattr(message_class, 'create') and callable(getattr(message_class, 'create')):
            # Извлекаем обязательные параметры для create()
            msg_type = data.get('type', 'general')
            sender = data.get('sender', '')
            # Остальные параметры передаем как kwargs
            kwargs = {k: v for k, v in data.items() if k not in ('type', 'sender')}
            instance = message_class.create(msg_type, sender, **kwargs)
        else:
            # Fallback на конструктор
            instance = message_class(**data)
        
        # Синхронизируем словарь (внутренний метод сам управляет _data)
        instance._sync_to_dict()
        
        return instance
    
    @staticmethod
    def from_json(json_str: str, message_class: type) -> 'Message':
        """
        Создает сообщение из JSON строки.
        
        Args:
            json_str: JSON строка
            message_class: Класс сообщения
            
        Returns:
            Экземпляр сообщения
        """
        data = json.loads(json_str)
        return MessageConverter.from_dict(data, message_class)
    
    @staticmethod
    def from_yaml(yaml_str: str, message_class: type) -> 'Message':
        """
        Создает сообщение из YAML строки.
        
        Args:
            yaml_str: YAML строка
            message_class: Класс сообщения
            
        Returns:
            Экземпляр сообщения
            
        Raises:
            ImportError: Если PyYAML не установлен
        """
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML is not installed. Install it with: pip install pyyaml")
        
        data = yaml.safe_load(yaml_str)
        return MessageConverter.from_dict(data, message_class)

