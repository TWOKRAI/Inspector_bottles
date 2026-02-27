"""
ProcessData - данные процесса для межпроцессного взаимодействия.

ProcessData - dataclass для межпроцессного взаимодействия.
Использует утилиты из data_schema для работы с данными.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Callable
from multiprocessing import Queue, Event

# Используем утилиты из data_schema
from ..Shared_resources_module.data_schema.utils import (
    get_nested_value,
    set_nested_value,
    convert_all_references,
)
from ..Shared_resources_module.data_schema.utils.reference import convert_reference_to_data
from ..Shared_resources_module.data_schema.models.types import ComponentType


class ProcessDataKeys:
    """
    Константы ключей для наглядного доступа к данным ProcessData.
    
    ProcessData как ДНК - хранит всю информацию о процессе.
    Эти константы делают код более читаемым и понятным.
    """
    
    # Ключи для custom данных
    CONSOLE_QUEUE = 'console_queue'
    CONSOLE_QUEUES = 'console_queues'
    CONSOLE_INFO = 'console_info'
    
    # Ключи для metadata
    METADATA_PRIORITY = 'priority'
    METADATA_CLASS_PATH = 'class_path'
    METADATA_PID = 'pid'
    METADATA_START_TIME = 'start_time'
    
    # Ключи для конфигурации процесса (хранится в custom)
    CONFIG_PROCESS = 'process_config'
    CONFIG_MANAGERS = 'component_managers_config'
    CONFIG_MODULES = 'modules_config'
    CONFIG_CUSTOM = 'config_custom'
    
    # Стандартные имена очередей
    QUEUE_SYSTEM = 'system'
    QUEUE_DATA = 'data'
    QUEUE_COMMANDS = 'commands'
    QUEUE_RESULTS = 'results'
    
    # Стандартные имена событий
    EVENT_START = 'start'
    EVENT_STOP = 'stop'
    EVENT_PAUSE = 'pause'
    EVENT_RESUME = 'resume'
    
    # Статусы процессов
    STATUS_INITIALIZING = 'initializing'
    STATUS_READY = 'ready'
    STATUS_RUNNING = 'running'
    STATUS_STOPPED = 'stopped'
    STATUS_ERROR = 'error'


class QueuesProxy:
    """
    Прокси-класс для удобного доступа к очередям через атрибуты.
    
    Позволяет обращаться к очередям как к атрибутам:
        process_data.queues.data.put(item)
        process_data.queues.system.get()
    """
    
    def __init__(self, queues: Dict[str, Queue] = None):
        if queues is None:
            queues = {}
        self._queues = queues
    
    def __getattr__(self, name: str) -> Optional[Queue]:
        try:
            queues_dict = object.__getattribute__(self, '_queues')
        except AttributeError:
            return None
        
        if name == '_queues':
            return queues_dict
        
        return queues_dict.get(name) if queues_dict else None
    
    def __setstate__(self, state):
        self._queues = state.get('_queues', {})
    
    def __getstate__(self):
        return {'_queues': self._queues}
    
    def __getitem__(self, name: str) -> Optional[Queue]:
        return self._queues.get(name)
    
    def __contains__(self, name: str) -> bool:
        return name in self._queues
    
    def __iter__(self):
        return iter(self._queues.keys())
    
    def __len__(self) -> int:
        return len(self._queues)
    
    def keys(self):
        return self._queues.keys()
    
    def values(self):
        return self._queues.values()
    
    def items(self):
        return self._queues.items()


class EventsProxy:
    """
    Прокси-класс для удобного доступа к событиям через атрибуты.
    
    Позволяет обращаться к событиям как к атрибутам:
        process_data.events.start.set()
        process_data.events.stop.wait()
    """
    
    def __init__(self, events: Dict[str, Event] = None):
        if events is None:
            events = {}
        self._events = events
    
    def __getattr__(self, name: str) -> Optional[Event]:
        try:
            events_dict = object.__getattribute__(self, '_events')
        except AttributeError:
            return None
        
        if name == '_events':
            return events_dict
        
        return events_dict.get(name) if events_dict else None
    
    def __setstate__(self, state):
        self._events = state.get('_events', {})
    
    def __getstate__(self):
        return {'_events': self._events}
    
    def __getitem__(self, name: str) -> Optional[Event]:
        return self._events.get(name)
    
    def __contains__(self, name: str) -> bool:
        return name in self._events
    
    def __iter__(self):
        return iter(self._events.keys())
    
    def __len__(self) -> int:
        return len(self._events)
    
    def keys(self):
        return self._events.keys()
    
    def values(self):
        return self._events.values()
    
    def items(self):
        return self._events.items()


@dataclass
class ProcessData:
    """
    Данные процесса для межпроцессного взаимодействия.
    
    ProcessData - dataclass для межпроцессной передачи данных.
    Поля:
    - component_type: Тип компонента (PROCESS)
    - component_class: Имя класса процесса
    - name: Имя процесса
    - status: Статус процесса
    - metadata: Метаданные процесса
    - version: Версия данных
    - created_at: Время создания
    - updated_at: Время последнего обновления
    - queues: Очереди для передачи данных (QueuesProxy)
    - events: События для синхронизации (EventsProxy)
    - custom: Кастомные данные (включая данные компонентов через DataManager)
    
    Использует утилиты из data_schema для работы с данными.
    
    Пример использования:
        # Доступ к очередям
        process_data.queues.data.put(item)
        
        # Доступ к событиям
        process_data.events.start.set()
        
        # Универсальные методы из data_schema.utils
        from multiprocess_framework.modules.Shared_resources_module.data_schema.utils import get_nested_value
        config_value = get_nested_value(process_data.custom, 'managers.logger_main.config.log_level')
        
        # Доступ к данным компонентов через DataManager (data_schema модуль)
        from multiprocess_framework.modules.Shared_resources_module.data_schema import DataManager
        data_manager = DataManager.get_instance()
        manager_config = data_manager.get_manager_config(
            "LoggerManager", 
            "logger_main", 
            "log_level", 
            process_name=process_data.name
        )
    """
    
    _queues_dict: Dict[str, Queue] = field(default_factory=dict, repr=False)
    _events_dict: Dict[str, Event] = field(default_factory=dict, repr=False)
    custom: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Инициализация после создания."""
        # Устанавливаем component_type если не установлен
        if self.component_type != ComponentType.PROCESS:
            self.component_type = ComponentType.PROCESS
        
        # Инициализация прокси-объектов для удобного доступа
        if self._queues_dict is None:
            self._queues_dict = {}
        if self._events_dict is None:
            self._events_dict = {}
        
        self._queues_proxy = QueuesProxy(self._queues_dict)
        self._events_proxy = EventsProxy(self._events_dict)
    
    def __setstate__(self, state):
        """Восстановление состояния при десериализации."""
        # Восстанавливаем базовые поля
        component_type_value = state.get('component_type', ComponentType.PROCESS.value)
        if isinstance(component_type_value, str):
            self.component_type = ComponentType(component_type_value)
        else:
            self.component_type = component_type_value
        self.component_class = state.get('component_class', '')
        self.name = state.get('name', '')
        self.status = state.get('status', 'initializing')
        self.metadata = state.get('metadata', {})
        self.version = state.get('version', time.time())
        self.created_at = state.get('created_at', time.time())
        self.updated_at = state.get('updated_at', time.time())
        
        # Восстанавливаем специфичные поля
        self._queues_dict = state.get('_queues_dict', {})
        self._events_dict = state.get('_events_dict', {})
        self.custom = state.get('custom', {})
        
        # Пересоздаем прокси-объекты
        self._queues_proxy = QueuesProxy(self._queues_dict)
        self._events_proxy = EventsProxy(self._events_dict)
    
    def __getstate__(self):
        """Сохранение состояния при сериализации."""
        return {
            'component_type': self.component_type.value,
            'component_class': self.component_class,
            'name': self.name,
            'status': self.status,
            'metadata': self.metadata,
            'version': self.version,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            '_queues_dict': self._queues_dict,
            '_events_dict': self._events_dict,
            'custom': self.custom
        }
    
    @property
    def queues(self) -> QueuesProxy:
        """Прокси для доступа к очередям через атрибуты."""
        return self._queues_proxy
    
    @property
    def events(self) -> EventsProxy:
        """Прокси для доступа к событиям через атрибуты."""
        return self._events_proxy
    
    def update_timestamp(self):
        """Обновляет timestamp текущим временем."""
        self.version = time.time()
        self.updated_at = time.time()
    
    def add_queue(self, queue_type: str, queue: Queue):
        """Добавляет очередь в словарь очередей."""
        self._queues_dict[queue_type] = queue
        self.update_timestamp()
    
    def add_event(self, event_name: str, event: Event):
        """Добавляет событие в словарь событий."""
        self._events_dict[event_name] = event
        self.update_timestamp()
    
    def get_queue(self, queue_type: str) -> Optional[Queue]:
        """Получает очередь по типу."""
        return self._queues_dict.get(queue_type)
    
    def get_event(self, event_name: str) -> Optional[Event]:
        """Получает событие по имени."""
        return self._events_dict.get(event_name)
    
    def update_custom(self, **kwargs):
        """Обновляет кастомные данные."""
        self.custom.update(kwargs)
        self.update_timestamp()
    
    # Методы для работы с данными через data_schema.utils
    def get_custom_value(self, key: str, default: Any = None) -> Any:
        """Получить значение из custom по точечной нотации."""
        return get_nested_value(self.custom, key, default)
    
    def set_custom_value(self, key: str, value: Any):
        """Установить значение в custom по точечной нотации."""
        set_nested_value(self.custom, key, value)
        self.update_timestamp()
    
    def convert_references_in_custom(self, resolver: Optional[Callable] = None):
        """Конвертировать все ссылки в custom в обычные данные."""
        self.custom = convert_all_references(self.custom, resolver)
        self.update_timestamp()
    
    def convert_reference_at_path(self, path: str, resolver: Optional[Callable] = None) -> bool:
        """Точечная конвертация ссылки по пути в custom."""
        # Разбиваем путь на части
        keys = path.split('.')
        current = self.custom
        
        # Находим объект по пути
        for key in keys[:-1]:
            if not isinstance(current, dict) or key not in current:
                return False
            current = current[key]
        
        # Конвертируем ссылку
        final_key = keys[-1]
        if isinstance(current, dict) and final_key in current:
            converted = convert_reference_to_data(current[final_key], resolver)
            if converted is not None:
                current[final_key] = converted
                self.update_timestamp()
                return True
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Конвертирует ProcessData в словарь для сериализации.
        
        ВАЖНО: Queue и Event не сериализуются в словарь,
        они остаются как объекты и передаются по ссылке.
        """
        # Конвертируем в словарь
        data = {
            "component_type": self.component_type.value if hasattr(self.component_type, 'value') else self.component_type,
            "component_class": self.component_class,
            "name": self.name,
            "status": self.status,
            "metadata": self.metadata.copy(),
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "custom": self.custom.copy(),
            "queues_count": len(self._queues_dict),
            "events_count": len(self._events_dict),
            "queue_types": list(self._queues_dict.keys()),
            "event_names": list(self._events_dict.keys())
        }
        return data
    
    def export_to_config(self) -> Dict[str, Any]:
        """
        Экспортирует ProcessData в формат конфигурации процесса.
        
        Создает конфиг-чертеж из существующей ProcessData (ДНК → чертеж).
        """
        config = {
            "name": self.name,
            "class": self.component_class or self.metadata.get(ProcessDataKeys.METADATA_CLASS_PATH, ""),
            "priority": self.metadata.get(ProcessDataKeys.METADATA_PRIORITY, "normal"),
            "enabled": True,
            "config": {}
        }
        
        # Копируем основную конфигурацию процесса из custom
        process_config = self.custom.get(ProcessDataKeys.CONFIG_PROCESS, {})
        if process_config:
            config["config"].update(process_config)
        
        # Добавляем конфигурацию очередей
        if self._queues_dict:
            config["queues"] = {}
            queues_config = process_config.get("queues", {})
            for queue_name in self._queues_dict.keys():
                queue_config = queues_config.get(queue_name, {}) if isinstance(queues_config, dict) else {}
                maxsize = queue_config.get("maxsize", 100) if isinstance(queue_config, dict) else 100
                config["queues"][queue_name] = {"maxsize": maxsize}
        
        # Добавляем конфигурацию консоли из custom
        if ProcessDataKeys.CONSOLE_INFO in self.custom:
            console_info = self.custom[ProcessDataKeys.CONSOLE_INFO]
            config["console"] = {
                "enabled": console_info.get("has_console", False),
                "title": console_info.get("title"),
                "recipient": console_info.get("recipients", [])
            }
        
        # Добавляем конфигурацию воркеров
        modules_config = self.custom.get(ProcessDataKeys.CONFIG_MODULES, {})
        if modules_config:
            workers = {}
            for module_name, module_config in modules_config.items():
                if "worker" in module_name.lower() or "worker" in str(module_config):
                    workers[module_name] = module_config
            if workers:
                config["workers"] = workers
        
        return config
