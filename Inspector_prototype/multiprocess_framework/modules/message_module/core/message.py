# -*- coding: utf-8 -*-
"""
Основной класс Message.

Публичный API модуля. Используется извне модуля.
"""

import time
from typing import Any, Dict, List, Optional, Union, Set, Type, TYPE_CHECKING

from ..types import (
    MessageType,
    Priority,
    LogLevel,
    MessageValidationError,
    VALID_MESSAGE_FIELDS,
    MESSAGE_FIELD_DEFAULTS,
)
from ..validators.message_validator import MessageValidator
from ..converters.message_converter import MessageConverter
from ..utils import generate_message_id, apply_type_defaults

if TYPE_CHECKING:
    from pydantic import BaseModel


class Message:
    """IPC value object: публичные методы без `_`, внутренние с `_`."""
    
    def __init__(self, **kwargs):
        """Предпочтительно ``Message.create()``; kwargs — поля сообщения."""
        _schema: Optional[Type['BaseModel']] = kwargs.pop('_schema', None)
        _schema_info: Optional[Dict[str, str]] = kwargs.pop('_schema_info', None)
        _schema_validated: bool = kwargs.pop('_schema_validated', False)

        raw_type = kwargs.pop('type', 'general')
        if isinstance(raw_type, MessageType):
            self.type = raw_type.value
        else:
            self.type = raw_type

        self.id = kwargs.pop('id', generate_message_id(self.type))
        self.sender = kwargs.pop('sender', '')
        self.targets = kwargs.pop('targets', [])
        self.timestamp = kwargs.pop('timestamp', time.time())

        for field, default in MESSAGE_FIELD_DEFAULTS.items():
            setattr(self, field, kwargs.pop(field, default))

        for key in list(kwargs.keys()):
            if key in VALID_MESSAGE_FIELDS:
                setattr(self, key, kwargs.pop(key))

        apply_type_defaults(self)

        self._schema = _schema
        self._schema_info = _schema_info
        self._schema_validated = _schema_validated

    @classmethod
    def create(
        cls,
        type: Union[MessageType, str],
        sender: str,
        schema: Optional[Type['BaseModel']] = None,
        **kwargs
    ) -> 'Message':
        """Создать сообщение; при ``schema`` — валидация Pydantic, иначе поля из kwargs."""
        if isinstance(type, MessageType):
            type = type.value
        
        # Если указана схема - используем валидацию через Pydantic
        if schema is not None:
            # Подготавливаем данные для схемы
            schema_data = {
                'type': type,
                'sender': sender,
                **kwargs
            }
            
            # Генерируем ID если не указан
            if 'id' not in schema_data:
                schema_data['id'] = generate_message_id(type)
            
            # Валидация через Pydantic (быстрая)
            try:
                validated = schema(**schema_data)
            except Exception as e:
                raise MessageValidationError(f"Schema validation failed: {e}") from e
            
            # Получаем информацию о схеме
            schema_info = validated.get_schema_info() if hasattr(validated, 'get_schema_info') else {
                'schema_name': schema.__name__,
                'schema_module': schema.__module__,
                'schema_path': f"{schema.__module__}.{schema.__name__}",
            }
            
            # Создаем сообщение из валидированных данных
            instance = cls(
                **validated.model_dump(),
                _schema=schema,
                _schema_info=schema_info,
                _schema_validated=True
            )
        else:
            # Стандартная логика (обратная совместимость)
            instance = cls(type=type, sender=sender, **kwargs)
        
        return instance

    def set_priority(self, priority: Union[Priority, str]) -> 'Message':
        """Устанавливает приоритет сообщения."""
        if isinstance(priority, Priority):
            priority = priority.value
        self.priority = priority
        return self
    
    def set_targets(self, targets: List[str]) -> 'Message':
        """Устанавливает список получателей."""
        self.targets = targets
        return self
    
    def add_target(self, target: str) -> 'Message':
        """Добавляет получателя."""
        if target not in self.targets:
            self.targets.append(target)
        return self
    
    def set_channel(self, channel: str) -> 'Message':
        """Устанавливает канал доставки."""
        self.channel = channel
        return self
    
    def set_content(self, content: Any) -> 'Message':
        """Устанавливает содержимое сообщения (для GENERAL)."""
        self.content = content
        return self
    
    def set_command(self, command: str, args: Dict[str, Any] = None) -> 'Message':
        """Устанавливает команду и аргументы (для COMMAND)."""
        self.command = command
        if args:
            self.args = args
        return self
    
    def set_log(self, level: Union[LogLevel, str], message: str, module: str = None) -> 'Message':
        """Устанавливает параметры лога (для LOG)."""
        if isinstance(level, LogLevel):
            level = level.value
        self.level = level
        self.message = message
        if module:
            self.module = module
        return self
    
    def add_metadata(self, key: str, value: Any) -> 'Message':
        """Добавляет метаданные."""
        self.metadata[key] = value
        return self

    def validate(self) -> bool:
        """Pydantic-схема или базовая проверка (sender, targets). ``MessageValidationError`` при ошибке."""
        # Если есть Pydantic схема - валидируем через неё
        if self._schema is not None:
            try:
                # Фильтруем данные по схеме - оставляем только разрешенные поля
                data = self.to_dict(exclude_none=False)
                schema_fields = set(self._schema.model_fields.keys())
                filtered_data = {k: v for k, v in data.items() if k in schema_fields}

                # Создаем временный экземпляр схемы для валидации
                self._schema(**filtered_data)
                return True
            except Exception as e:
                raise MessageValidationError(f"Schema validation failed: {e}") from e

        # Стандартная валидация (базовые правила: sender, targets)
        return MessageValidator.validate(self)

    def is_valid(self) -> bool:
        """Как validate(), но без исключения — только bool."""
        return MessageValidator.is_valid(self)

    def to_dict(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None
    ) -> Dict[str, Any]:
        """Конвертирует сообщение в словарь."""
        return MessageConverter.to_dict(self, exclude_none, exclude_fields, include_fields)
    
    def to_json(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None,
        indent: Optional[int] = None
    ) -> str:
        """Конвертирует сообщение в JSON строку."""
        return MessageConverter.to_json(self, exclude_none, exclude_fields, include_fields, indent)
    
    def to_yaml(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None
    ) -> str:
        """Конвертирует сообщение в YAML строку."""
        return MessageConverter.to_yaml(self, exclude_none, exclude_fields, include_fields)
    
    def to_text(
        self,
        exclude_none: bool = True,
        exclude_fields: Optional[Set[str]] = None,
        include_fields: Optional[Set[str]] = None
    ) -> str:
        """Конвертирует сообщение в текстовый формат."""
        return MessageConverter.to_text(self, exclude_none, exclude_fields, include_fields)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], schema: Optional[Type['BaseModel']] = None) -> 'Message':
        """Собрать из dict; при ``schema`` — через Pydantic."""
        if schema is not None:
            # Фильтруем данные по схеме - оставляем только разрешенные поля
            schema_fields = set(schema.model_fields.keys())
            filtered_data = {k: v for k, v in data.items() if k in schema_fields}
            
            # Валидация через схему
            validated = schema(**filtered_data)
            schema_info = validated.get_schema_info() if hasattr(validated, 'get_schema_info') else {
                'schema_name': schema.__name__,
                'schema_module': schema.__module__,
                'schema_path': f"{schema.__module__}.{schema.__name__}",
            }
            return cls(
                **validated.model_dump(),
                _schema=schema,
                _schema_info=schema_info,
                _schema_validated=True
            )
        else:
            # Стандартная логика
            return MessageConverter.from_dict(data, cls)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        """Создает сообщение из JSON строки."""
        return MessageConverter.from_json(json_str, cls)
    
    @classmethod
    def from_yaml(cls, yaml_str: str) -> 'Message':
        """Создает сообщение из YAML строки."""
        return MessageConverter.from_yaml(yaml_str, cls)

    def get_type(self) -> Optional[MessageType]:
        """Возвращает тип сообщения как enum."""
        try:
            return MessageType(self.type)
        except ValueError:
            return None
    
    def get_priority(self) -> Priority:
        """Возвращает приоритет как enum."""
        try:
            return Priority(self.priority)
        except ValueError:
            return Priority.NORMAL
    
    def clone(self) -> 'Message':
        """Создает копию сообщения с новым ID."""
        data = self.to_dict(exclude_none=False)
        data['id'] = generate_message_id(self.type)
        data['timestamp'] = time.time()
        # Сохраняем схему при клонировании
        # from_dict уже фильтрует данные по схеме
        cloned = Message.from_dict(data, schema=self._schema)
        # Сохраняем информацию о схеме
        if self._schema_info:
            cloned._schema_info = self._schema_info.copy()
        return cloned

    def __getitem__(self, key: str) -> Any:
        """Доступ к полям сообщения как к словарю: msg['command']."""
        if key not in VALID_MESSAGE_FIELDS:
            raise KeyError(key)
        if not hasattr(self, key):
            raise KeyError(key)
        return getattr(self, key)
    
    def __contains__(self, key: str) -> bool:
        """Проверка наличия ключа: 'command' in msg."""
        return key in VALID_MESSAGE_FIELDS and hasattr(self, key)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Как dict.get: отсутствующий атрибут → default."""
        return getattr(self, key, default)
    
    def keys(self):
        """Возвращает итератор по ключам сообщения."""
        return [f for f in VALID_MESSAGE_FIELDS if hasattr(self, f)]
    
    def values(self):
        """Возвращает итератор по значениям сообщения."""
        return [getattr(self, f, None) for f in VALID_MESSAGE_FIELDS if hasattr(self, f)]
    
    def items(self):
        """Возвращает итератор по парам (ключ, значение)."""
        return [(f, getattr(self, f, None)) for f in VALID_MESSAGE_FIELDS if hasattr(self, f)]
    
    def __setitem__(self, key: str, value: Any):
        """Запись поля; неизвестное имя → KeyError."""
        if key not in VALID_MESSAGE_FIELDS:
            raise KeyError(
                f"Field '{key}' is not a valid message field. "
                f"Valid fields: {sorted(VALID_MESSAGE_FIELDS)}"
            )
        
        setattr(self, key, value)
    
    def get_schema_info(self) -> Optional[Dict[str, str]]:
        """Метаданные Pydantic-схемы или None."""
        return self._schema_info

    def get_schema(self) -> Optional[Type['BaseModel']]:
        """Класс Pydantic-схемы или None."""
        return self._schema
    
    def __repr__(self) -> str:
        """Строковое представление сообщения."""
        main_fields = ['type', 'id', 'sender', 'targets']
        parts = []
        for k in main_fields:
            if hasattr(self, k):
                parts.append(f"{k}={repr(getattr(self, k))}")
        fields_str = ', '.join(parts)
        schema_info = f", schema={self._schema_info['schema_name']}" if self._schema_info else ""
        return f"Message({fields_str}{schema_info})"
    
    def __str__(self) -> str:
        """Человекочитаемое представление."""
        return self.to_text()

