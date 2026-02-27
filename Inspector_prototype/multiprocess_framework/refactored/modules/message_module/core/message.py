"""
Основной класс Message.

Публичный API модуля. Используется извне модуля.
"""

import time
from typing import Any, Dict, List, Optional, Union, Set, Type, TYPE_CHECKING

from ..types import MessageType, Priority, LogLevel, MessageValidationError, VALID_MESSAGE_FIELDS
from ..validators.message_validator import MessageValidator
from ..converters.message_converter import MessageConverter
from ..utils import generate_message_id, apply_type_defaults

if TYPE_CHECKING:
    from pydantic import BaseModel


class Message:
    """
    Универсальный класс для работы с сообщениями.
    
    Публичный API модуля. Используется извне модуля.
    
    Разделение методов:
    - Публичные методы (используются извне) - без префикса _
    - Внутренние методы (используются только внутри класса) - с префиксом _
    """
    
    def __init__(self, **kwargs):
        """
        Инициализация сообщения.
        
        Прямая инициализация не рекомендуется.
        Используйте Message.create() для создания сообщений.
        
        Args:
            **kwargs: Поля сообщения
        """
        # Обязательные поля
        self.id: str = kwargs.get('id', generate_message_id(kwargs.get('type', 'general')))
        self.type: str = kwargs.get('type', 'general')
        self.sender: str = kwargs.get('sender', '')
        self.targets: List[str] = kwargs.get('targets', [])
        self.timestamp: float = kwargs.get('timestamp', time.time())
        
        # Опциональные поля
        self.priority: str = kwargs.get('priority', 'normal')
        self.routers: List[str] = kwargs.get('routers', ['internal'])
        self.channel: Optional[str] = kwargs.get('channel', None)
        self.metadata: Dict[str, Any] = kwargs.get('metadata', {})
        
        # Специфичные поля для разных типов
        self.content: Any = kwargs.get('content', None)
        self.command: Optional[str] = kwargs.get('command', None)
        self.args: Dict[str, Any] = kwargs.get('args', {})
        self.need_ack: bool = kwargs.get('need_ack', False)
        self.level: Optional[str] = kwargs.get('level', None)
        self.message: Optional[str] = kwargs.get('message', None)
        self.module: str = kwargs.get('module', 'main')
        self.action: Optional[str] = kwargs.get('action', None)
        self.data: Any = kwargs.get('data', None)
        self.exclude: List[str] = kwargs.get('exclude', [])
        self.data_type: Optional[str] = kwargs.get('data_type', None)
        self.use_shared_memory: bool = kwargs.get('use_shared_memory', False)
        self.memory_key: Optional[str] = kwargs.get('memory_key', None)
        self.request_type: Optional[str] = kwargs.get('request_type', None)
        self.query: Any = kwargs.get('query', None)
        self.timeout: float = kwargs.get('timeout', 5.0)
        self.request_id: Optional[str] = kwargs.get('request_id', None)
        self.success: bool = kwargs.get('success', True)
        self.result: Any = kwargs.get('result', None)
        self.error: Optional[str] = kwargs.get('error', None)
        self.event_type: Optional[str] = kwargs.get('event_type', None)
        self.event_data: Any = kwargs.get('event_data', None)
        
        # Применяем дефолты для типа
        apply_type_defaults(self)
        
        # Внутренний словарь для O(1) доступа (ленивая синхронизация)
        self._data: Optional[Dict[str, Any]] = None
        self._data_synced: bool = False
        
        # Информация о схеме (для производительности и отслеживания)
        self._schema: Optional[Type['BaseModel']] = kwargs.pop('_schema', None)
        self._schema_info: Optional[Dict[str, str]] = kwargs.pop('_schema_info', None)
        self._schema_validated: bool = kwargs.pop('_schema_validated', False)
    
    # ========================================================================
    # ВНУТРЕННИЕ МЕТОДЫ (не используются извне)
    # ========================================================================
    
    def _sync_to_dict(self):
        """
        Синхронизирует атрибуты объекта в внутренний словарь _data для O(1) доступа.
        
        Внутренний метод - не предназначен для использования извне.
        Фильтрует только допустимые поля из схемы сообщения.
        """
        if self._data_synced and self._data is not None:
            return
        
        # Фильтруем только допустимые поля из схемы
        all_attrs = {
            key: value for key, value in self.__dict__.items()
            if not key.startswith('_') and key in VALID_MESSAGE_FIELDS
        }
        
        self._data = all_attrs
        self._data_synced = True
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - ФАБРИЧНЫЙ МЕТОД
    # ========================================================================
    
    @classmethod
    def create(
        cls,
        type: Union[MessageType, str],
        sender: str,
        schema: Optional[Type['BaseModel']] = None,
        **kwargs
    ) -> 'Message':
        """
        Фабричный метод для создания сообщений.
        
        Поддерживает опциональную схему (Pydantic) для валидации.
        Если схема не указана, используется стандартная логика (обратная совместимость).
        
        Args:
            type: Тип сообщения (MessageType enum или строка)
            sender: Отправитель сообщения
            schema: Опциональная схема Pydantic для валидации
            **kwargs: Дополнительные параметры сообщения
            
        Returns:
            Message: Новый экземпляр сообщения
            
        Example:
            >>> from multiprocess_framework.refactored.modules.message.schemas import CommandMessageSchema
            >>> msg = Message.create(
            ...     MessageType.COMMAND,
            ...     sender="sender",
            ...     schema=CommandMessageSchema,
            ...     targets=["target"],
            ...     command="test"
            ... )
        """
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
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - FLUENT API ДЛЯ НАПОЛНЕНИЯ ДАННЫМИ
    # ========================================================================
     
    def set_priority(self, priority: Union[Priority, str]) -> 'Message':
        """Устанавливает приоритет сообщения."""
        if isinstance(priority, Priority):
            priority = priority.value
        self.priority = priority
        self._data_synced = False
        return self
    
    def set_targets(self, targets: List[str]) -> 'Message':
        """Устанавливает список получателей."""
        self.targets = targets
        self._data_synced = False
        return self
    
    def add_target(self, target: str) -> 'Message':
        """Добавляет получателя."""
        if target not in self.targets:
            self.targets.append(target)
            self._data_synced = False
        return self
    
    def set_channel(self, channel: str) -> 'Message':
        """Устанавливает канал доставки."""
        self.channel = channel
        self._data_synced = False
        return self
    
    def set_content(self, content: Any) -> 'Message':
        """Устанавливает содержимое сообщения (для GENERAL)."""
        self.content = content
        self._data_synced = False
        return self
    
    def set_command(self, command: str, args: Dict[str, Any] = None) -> 'Message':
        """Устанавливает команду и аргументы (для COMMAND)."""
        self.command = command
        self._data_synced = False
        if args:
            self.args = args
        return self
    
    def set_log(self, level: Union[LogLevel, str], message: str, module: str = None) -> 'Message':
        """Устанавливает параметры лога (для LOG)."""
        if isinstance(level, LogLevel):
            level = level.value
        self.level = level
        self.message = message
        self._data_synced = False
        if module:
            self.module = module
        return self
    
    def add_metadata(self, key: str, value: Any) -> 'Message':
        """Добавляет метаданные."""
        self.metadata[key] = value
        self._data_synced = False
        return self
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - ВАЛИДАЦИЯ
    # ========================================================================
    
    def validate(self) -> bool:
        """
        Валидирует сообщение перед отправкой.
        
        Если сообщение было создано со схемой и уже прошло валидацию,
        пропускает повторную валидацию для производительности.
        
        Returns:
            bool: True если валидно
            
        Raises:
            MessageValidationError: Если сообщение невалидно
        """
        # Если уже валидировано через схему - пропускаем (производительность)
        if self._schema_validated and self._schema is not None:
            # Быстрая проверка через схему (если нужно)
            try:
                # Фильтруем данные по схеме - оставляем только разрешенные поля
                data = self.to_dict(exclude_none=False)
                schema_fields = set(self._schema.model_fields.keys())
                filtered_data = {k: v for k, v in data.items() if k in schema_fields}
                
                # Создаем временный экземпляр схемы для быстрой валидации
                self._schema(**filtered_data)
                return True
            except Exception as e:
                raise MessageValidationError(f"Schema validation failed: {e}") from e
        
        # Стандартная валидация (обратная совместимость)
        return MessageValidator.validate(self)
    
    def is_valid(self) -> bool:
        """
        Проверяет валидность сообщения без выброса исключения.
        
        Returns:
            bool: True если валидно, False иначе
        """
        return MessageValidator.is_valid(self)
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - КОНВЕРТАЦИЯ
    # ========================================================================
    
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
        """
        Создает сообщение из словаря.
        
        Args:
            data: Словарь с данными сообщения
            schema: Опциональная схема для валидации
            
        Returns:
            Message: Экземпляр сообщения
        """
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
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
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
    
    # ========================================================================
    # ПУБЛИЧНЫЙ API - СЛОВАРНЫЙ ИНТЕРФЕЙС
    # ========================================================================
    
    def __getitem__(self, key: str) -> Any:
        """Доступ к полям сообщения как к словарю: msg['command']."""
        self._sync_to_dict()
        return self._data[key]
    
    def __contains__(self, key: str) -> bool:
        """Проверка наличия ключа: 'command' in msg."""
        self._sync_to_dict()
        return key in self._data
    
    def get(self, key: str, default: Any = None) -> Any:
        """Безопасный доступ к полю с дефолтным значением."""
        self._sync_to_dict()
        # Если ключа нет в _data, возвращаем default
        # Если ключ есть но значение None, тоже возвращаем default (если default не None)
        if key not in self._data:
            return default
        value = self._data[key]
        # Если значение None и передан default, возвращаем default
        if value is None and default is not None:
            return default
        return value
    
    def keys(self):
        """Возвращает итератор по ключам сообщения."""
        self._sync_to_dict()
        return self._data.keys()
    
    def values(self):
        """Возвращает итератор по значениям сообщения."""
        self._sync_to_dict()
        return self._data.values()
    
    def items(self):
        """Возвращает итератор по парам (ключ, значение)."""
        self._sync_to_dict()
        return self._data.items()
    
    def __setitem__(self, key: str, value: Any):
        """
        Установка значения поля: msg['command'] = 'process'.
        
        Валидирует, что поле существует в схеме сообщения.
        
        Args:
            key: Имя поля
            value: Значение поля
            
        Raises:
            KeyError: Если поле не существует в схеме сообщения
        """
        if key not in VALID_MESSAGE_FIELDS:
            raise KeyError(
                f"Field '{key}' is not a valid message field. "
                f"Valid fields: {sorted(VALID_MESSAGE_FIELDS)}"
            )
        
        setattr(self, key, value)
        self._data_synced = False
    
    def get_schema_info(self) -> Optional[Dict[str, str]]:
        """
        Возвращает информацию о схеме сообщения.
        
        Returns:
            Словарь с информацией о схеме (schema_name, schema_module, schema_path)
            или None если схема не использовалась
        """
        return self._schema_info
    
    def get_schema(self) -> Optional[Type['BaseModel']]:
        """
        Возвращает класс схемы, использованной при создании сообщения.
        
        Returns:
            Класс схемы или None если схема не использовалась
        """
        return self._schema
    
    def __repr__(self) -> str:
        """Строковое представление сообщения."""
        self._sync_to_dict()
        main_fields = ['type', 'id', 'sender', 'targets']
        fields_str = ', '.join(f"{k}={repr(self._data.get(k, 'N/A'))}" for k in main_fields if k in self._data)
        schema_info = f", schema={self._schema_info['schema_name']}" if self._schema_info else ""
        return f"Message({fields_str}{schema_info})"
    
    def __str__(self) -> str:
        """Человекочитаемое представление."""
        return self.to_text()

