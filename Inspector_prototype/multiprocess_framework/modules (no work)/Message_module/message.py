"""
Единый класс для работы с сообщениями в системе межпроцессного взаимодействия.

Философия:
- Один класс Message для всех типов сообщений
- Фабричный метод create() для создания сообщений разных типов
- Fluent API для наполнения данными
- Методы конвертации для получения разных представлений
- Валидация перед отправкой
- Отправка делегируется роутеру (router.send(message))

Пример использования:
    # Создание сообщения
    msg = Message.create(
        type=MessageType.COMMAND,
        sender="GUI",
        targets=["Worker"],
        command="process_image",
        args={"image_id": 123}
    )
    
    # Наполнение дополнительными данными
    msg.set_priority(Priority.HIGH)
    msg.add_metadata("user_id", "12345")
    
    # Получение данных
    data = msg.to_dict()
    json_str = msg.to_json()
    
    # Отправка через роутер
    router.send(msg)
"""

import uuid
import time
import json
from typing import Any, Dict, List, Optional, Union, Set
from dataclasses import dataclass, field, asdict

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

from .message_types import (
    MessageType, 
    Priority, 
    LogLevel,
    MessageSchema,
    MESSAGE_TYPE_DEFAULTS,
    MESSAGE_TYPE_EXCLUDE_FIELDS
)


class MessageValidationError(ValueError):
    """Исключение для ошибок валидации сообщений."""
    pass


class Message:
    """
    Универсальный класс для работы с сообщениями.
    
    Инкапсулирует всю логику создания, валидации и конвертации сообщений.
    Поддерживает все типы сообщений через единый интерфейс.
    """
    
    def __init__(self, **kwargs):
        """
        Прямая инициализация не рекомендуется.
        Используйте Message.create() для создания сообщений.
        
        Args:
            **kwargs: Поля сообщения
        """
        # Обязательные поля
        self.id: str = kwargs.get('id', self._generate_id(kwargs.get('type', 'general')))
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
        self._apply_type_defaults()
        
        # Внутренний словарь для O(1) доступа (ленивая синхронизация для производительности)
        self._data: Optional[Dict[str, Any]] = None
        self._data_synced: bool = False
    
    @staticmethod
    def _generate_id(msg_type: str) -> str:
        """Генерирует уникальный ID для сообщения."""
        prefix_map = {
            'general': 'gen',
            'command': 'cmd',
            'log': 'log',
            'system': 'sys',
            'broadcast': 'brd',
            'data': 'dat',
            'request': 'req',
            'response': 'res',
            'event': 'evt',
        }
        prefix = prefix_map.get(msg_type, 'msg')
        return f"{prefix}_{uuid.uuid4().hex[:8]}"
    
    def _apply_type_defaults(self):
        """Применяет дефолтные значения для конкретного типа сообщения."""
        try:
            msg_type = MessageType(self.type)
            defaults = MESSAGE_TYPE_DEFAULTS.get(msg_type, {})
            
            # Применяем дефолты только если значение не было задано
            if 'channel' in defaults and self.channel is None:
                self.channel = defaults['channel']
            
            if 'targets' in defaults and not self.targets:
                self.targets = defaults['targets']
            
            if 'routers' in defaults:
                self.routers = defaults['routers']
                
        except ValueError:
            # Неизвестный тип, используем дефолты
            pass
    
    def _sync_to_dict(self):
        """
        Синхронизирует атрибуты объекта в внутренний словарь _data для O(1) доступа.
        Ленивая синхронизация - вызывается только при первом обращении через словарный интерфейс.
        Это оптимизирует создание и изменение сообщений.
        """
        if self._data_synced and self._data is not None:
            return  # Уже синхронизировано
        
        # Получаем все атрибуты объекта (исключая приватные)
        all_attrs = {key: value for key, value in self.__dict__.items() if not key.startswith('_')}
        # Убеждаемся что служебные поля не включены
        all_attrs.pop('_data', None)
        all_attrs.pop('_data_synced', None)
        
        self._data = all_attrs
        self._data_synced = True
    
    # ========================================================================
    # ФАБРИЧНЫЙ МЕТОД
    # ========================================================================
    
    @classmethod
    def create(cls, type: Union[MessageType, str], sender: str, **kwargs) -> 'Message':
        """
        Фабричный метод для создания сообщений.
        
        Args:
            type: Тип сообщения (MessageType enum или строка)
            sender: Отправитель сообщения
            **kwargs: Дополнительные параметры сообщения
            
        Returns:
            Message: Новый экземпляр сообщения
            
        Example:
            msg = Message.create(
                type=MessageType.COMMAND,
                sender="GUI",
                targets=["Worker"],
                command="process",
                args={"id": 123}
            )
        """
        # Конвертируем enum в строку если нужно
        if isinstance(type, MessageType):
            type = type.value
        
        return cls(type=type, sender=sender, **kwargs)
    
    # ========================================================================
    # FLUENT API ДЛЯ НАПОЛНЕНИЯ ДАННЫМИ
    # ========================================================================
     
    def set_priority(self, priority: Union[Priority, str]) -> 'Message':
        """Устанавливает приоритет сообщения."""
        if isinstance(priority, Priority):
            priority = priority.value
        self.priority = priority
        # Инвалидируем _data для ленивой синхронизации (обновится при следующем обращении)
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
    
    def set_routers(self, routers: List[str]) -> 'Message':
        """Устанавливает список роутеров."""
        self.routers = routers
        self._data_synced = False
        return self
    
    def add_router(self, router: str) -> 'Message':
        """Добавляет роутер."""
        if router not in self.routers:
            self.routers.append(router)
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
    
    def set_args(self, args: Dict[str, Any]) -> 'Message':
        """Устанавливает аргументы команды."""
        self.args = args
        self._data_synced = False
        return self
    
    def add_arg(self, key: str, value: Any) -> 'Message':
        """Добавляет аргумент команды."""
        self.args[key] = value
        self._data_synced = False
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
    
    def set_system_action(self, action: str, data: Any = None) -> 'Message':
        """Устанавливает системное действие (для SYSTEM)."""
        self.action = action
        self._data_synced = False
        if data is not None:
            self.data = data
        return self
    
    def set_data(self, data: Any, data_type: str = None) -> 'Message':
        """Устанавливает данные (для DATA и других типов)."""
        self.data = data
        self._data_synced = False
        if data_type:
            self.data_type = data_type
        return self
    
    def set_event(self, event_type: str, event_data: Any = None) -> 'Message':
        """Устанавливает событие (для EVENT)."""
        self.event_type = event_type
        self._data_synced = False
        if event_data is not None:
            self.event_data = event_data
        return self
    
    def add_metadata(self, key: str, value: Any) -> 'Message':
        """Добавляет метаданные."""
        self.metadata[key] = value
        self._data_synced = False
        return self
    
    def set_metadata(self, metadata: Dict[str, Any]) -> 'Message':
        """Устанавливает все метаданные."""
        self.metadata = metadata
        self._data_synced = False
        return self
    
    def set_need_ack(self, need_ack: bool = True) -> 'Message':
        """Устанавливает флаг необходимости подтверждения."""
        self.need_ack = need_ack
        self._data_synced = False
        return self
    
    # ========================================================================
    # ВАЛИДАЦИЯ
    # ========================================================================
    
    def validate(self) -> bool:
        """
        Валидирует сообщение перед отправкой.
        
        Returns:
            bool: True если валидно
            
        Raises:
            MessageValidationError: Если сообщение невалидно
        """
        # Базовая валидация
        if not self.sender:
            raise MessageValidationError("Sender cannot be empty")
        
        if not self.targets:
            raise MessageValidationError("Targets cannot be empty")
        
        # Валидация специфичных полей по типу
        try:
            msg_type = MessageType(self.type)
            defaults = MESSAGE_TYPE_DEFAULTS.get(msg_type, {})
            required_fields = defaults.get('required_fields', [])
            
            for field_name in required_fields:
                value = getattr(self, field_name, None)
                if value is None or (isinstance(value, str) and not value):
                    raise MessageValidationError(
                        f"Required field '{field_name}' is empty for message type '{self.type}'"
                    )
        
        except ValueError:
            raise MessageValidationError(f"Unknown message type: {self.type}")
        
        return True
    
    def is_valid(self) -> bool:
        """
        Проверяет валидность сообщения без выброса исключения.
        
        Returns:
            bool: True если валидно, False иначе
        """
        try:
            self.validate()
            return True
        except MessageValidationError:
            return False
    
    # ========================================================================
    # КОНВЕРТАЦИЯ В РАЗЛИЧНЫЕ ФОРМАТЫ
    # ========================================================================
    
    def to_dict(self, exclude_none: bool = True, 
                exclude_fields: Optional[Set[str]] = None,
                include_fields: Optional[Set[str]] = None) -> Dict[str, Any]:
        """
        Конвертирует сообщение в словарь.
        Оптимизировано для производительности - использует внутренний _data словарь с ленивой синхронизацией.
        
        Args:
            exclude_none: Исключать поля со значением None
            exclude_fields: Множество полей для исключения
            include_fields: Множество полей для включения (если задано, включаются только эти поля)
            
        Returns:
            Dict: Словарь с данными сообщения
        """
        # Ленивая синхронизация - заполняем _data только при первом обращении
        self._sync_to_dict()
        
        data = self._data.copy()  # Shallow copy для безопасности
        
        # Применяем exclude_fields для типа сообщения
        try:
            msg_type = MessageType(self.type)
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
    
    def to_json(self, exclude_none: bool = True,
                exclude_fields: Optional[Set[str]] = None,
                include_fields: Optional[Set[str]] = None,
                indent: Optional[int] = None) -> str:
        """
        Конвертирует сообщение в JSON строку.
        
        Args:
            exclude_none: Исключать поля со значением None
            exclude_fields: Множество полей для исключения
            include_fields: Множество полей для включения
            indent: Отступ для форматирования (None = компактный вывод)
            
        Returns:
            str: JSON строка
        """
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        return json.dumps(data, indent=indent, ensure_ascii=False)
    
    def to_yaml(self, exclude_none: bool = True,
                exclude_fields: Optional[Set[str]] = None,
                include_fields: Optional[Set[str]] = None) -> str:
        """
        Конвертирует сообщение в YAML строку.
        
        Args:
            exclude_none: Исключать поля со значением None
            exclude_fields: Множество полей для исключения
            include_fields: Множество полей для включения
            
        Returns:
            str: YAML строка
            
        Raises:
            ImportError: Если PyYAML не установлен
        """
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML is not installed. Install it with: pip install pyyaml")
        
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        return yaml.dump(data, allow_unicode=True, default_flow_style=False)
    
    def to_text(self, exclude_none: bool = True,
                exclude_fields: Optional[Set[str]] = None,
                include_fields: Optional[Set[str]] = None) -> str:
        """
        Конвертирует сообщение в текстовый формат (key: value).
        
        Args:
            exclude_none: Исключать поля со значением None
            exclude_fields: Множество полей для исключения
            include_fields: Множество полей для включения
            
        Returns:
            str: Текстовое представление
        """
        data = self.to_dict(exclude_none, exclude_fields, include_fields)
        lines = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            lines.append(f"{key}: {value}")
        return "\n".join(lines)
    
    # ========================================================================
    # ПАРСИНГ ИЗ РАЗЛИЧНЫХ ФОРМАТОВ
    # ========================================================================
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Message':
        """
        Создает сообщение из словаря.
        Оптимизировано для производительности - использует переданный словарь напрямую как _data.
        
        Args:
            data: Словарь с данными сообщения
            
        Returns:
            Message: Новый экземпляр сообщения
        """
        # Используем обычный __init__ для корректной инициализации
        instance = cls(**data)
        
        # Используем переданный словарь напрямую как _data (shallow copy для безопасности)
        # Это позволяет избежать повторного создания словаря и ускоряет создание
        instance._data = data.copy()
        instance._data_synced = True
        
        # Синхронизируем _data с атрибутами (на случай если были применены дефолты в _apply_type_defaults)
        # Но только если дефолты изменили значения
        if instance.channel != data.get('channel') or \
           instance.targets != data.get('targets') or \
           instance.routers != data.get('routers'):
            instance._sync_to_dict()
        
        return instance
    
    @classmethod
    def from_json(cls, json_str: str) -> 'Message':
        """
        Создает сообщение из JSON строки.
        
        Args:
            json_str: JSON строка
            
        Returns:
            Message: Новый экземпляр сообщения
        """
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    @classmethod
    def from_yaml(cls, yaml_str: str) -> 'Message':
        """
        Создает сообщение из YAML строки.
        
        Args:
            yaml_str: YAML строка
            
        Returns:
            Message: Новый экземпляр сообщения
            
        Raises:
            ImportError: Если PyYAML не установлен
        """
        if not YAML_AVAILABLE:
            raise ImportError("PyYAML is not installed. Install it with: pip install pyyaml")
        
        data = yaml.safe_load(yaml_str)
        return cls.from_dict(data)
    
    # ========================================================================
    # ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ
    # ========================================================================
    
    def get_type(self) -> MessageType:
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
    
    def get_log_level(self) -> Optional[LogLevel]:
        """Возвращает уровень лога как enum (для LOG сообщений)."""
        if self.level:
            try:
                return LogLevel(self.level)
            except ValueError:
                return None
        return None
    
    def clone(self) -> 'Message':
        """Создает копию сообщения с новым ID."""
        data = self.to_dict(exclude_none=False)
        data['id'] = self._generate_id(self.type)
        data['timestamp'] = time.time()
        return Message.from_dict(data)
    
    # ========================================================================
    # СЛОВАРНЫЙ ИНТЕРФЕЙС ДЛЯ O(1) ДОСТУПА
    # ========================================================================
    
    def __getitem__(self, key: str) -> Any:
        """
        Доступ к полям сообщения как к словарю: msg['command'].
        O(1) доступ через внутренний _data словарь с ленивой синхронизацией.
        
        Args:
            key: Ключ поля
            
        Returns:
            Значение поля
            
        Raises:
            KeyError: Если ключ не найден
        """
        self._sync_to_dict()
        return self._data[key]
    
    def __contains__(self, key: str) -> bool:
        """
        Проверка наличия ключа: 'command' in msg.
        O(1) проверка через внутренний _data словарь с ленивой синхронизацией.
        
        Args:
            key: Ключ для проверки
            
        Returns:
            True если ключ существует
        """
        self._sync_to_dict()
        return key in self._data
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Безопасный доступ к полю с дефолтным значением: msg.get('command', 'default').
        O(1) доступ через внутренний _data словарь с ленивой синхронизацией.
        
        Args:
            key: Ключ поля
            default: Значение по умолчанию если ключ не найден
            
        Returns:
            Значение поля или default
        """
        self._sync_to_dict()
        return self._data.get(key, default)
    
    def keys(self):
        """Возвращает итератор по ключам сообщения. O(1) через _data с ленивой синхронизацией."""
        self._sync_to_dict()
        return self._data.keys()
    
    def values(self):
        """Возвращает итератор по значениям сообщения. O(1) через _data с ленивой синхронизацией."""
        self._sync_to_dict()
        return self._data.values()
    
    def items(self):
        """Возвращает итератор по парам (ключ, значение). O(1) через _data с ленивой синхронизацией."""
        self._sync_to_dict()
        return self._data.items()
    
    def __setitem__(self, key: str, value: Any):
        """
        Установка значения поля: msg['command'] = 'process'.
        Обновляет атрибут и инвалидирует _data для ленивой синхронизации.
        
        Args:
            key: Ключ поля
            value: Значение поля
        """
        setattr(self, key, value)
        self._data_synced = False
    
    def __repr__(self) -> str:
        """Строковое представление сообщения (dataclass-подобное)."""
        self._sync_to_dict()
        # Показываем основные поля для краткости
        main_fields = ['type', 'id', 'sender', 'targets']
        fields_str = ', '.join(f"{k}={repr(self._data.get(k, 'N/A'))}" for k in main_fields if k in self._data)
        return f"Message({fields_str})"
    
    def __str__(self) -> str:
        """Человекочитаемое представление."""
        return self.to_text()


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================

def create_message(type: Union[MessageType, str], sender: str, **kwargs) -> Message:
    """
    Удобная функция для создания сообщений.
    Алиас для Message.create().
    
    Args:
        type: Тип сообщения
        sender: Отправитель
        **kwargs: Дополнительные параметры
        
    Returns:
        Message: Новый экземпляр сообщения
    """
    return Message.create(type=type, sender=sender, **kwargs)


def parse_message(data: Union[str, Dict[str, Any]]) -> Message:
    """
    Парсит сообщение из строки или словаря.
    Автоматически определяет формат (JSON, YAML, dict).
    
    Args:
        data: Данные для парсинга
        
    Returns:
        Message: Экземпляр сообщения
    """
    if isinstance(data, dict):
        return Message.from_dict(data)
    
    # Пробуем JSON
    try:
        return Message.from_json(data)
    except (json.JSONDecodeError, TypeError):
        pass
    
    # Пробуем YAML
    if YAML_AVAILABLE:
        try:
            return Message.from_yaml(data)
        except Exception:
            pass
    
    raise ValueError("Unable to parse message from provided data")

