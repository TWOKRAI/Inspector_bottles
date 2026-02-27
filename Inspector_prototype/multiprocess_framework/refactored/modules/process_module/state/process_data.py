"""
ProcessData - данные процесса для межпроцессного взаимодействия (Refactored).

Упрощенная версия без зависимостей от старого модуля.
Использует только стандартные библиотеки Python.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from multiprocessing import Queue, Event


class ProcessDataKeys:
    """
    Константы ключей для наглядного доступа к данным ProcessData.
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
    """
    
    def __init__(self, queues: Dict[str, Queue] = None):
        if queues is None:
            queues = {}
        self._queues = queues
    
    def __getattr__(self, name: str) -> Optional[Queue]:
        if name == '_queues':
            return self._queues
        return self._queues.get(name) if self._queues else None
    
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
    """
    
    def __init__(self, events: Dict[str, Event] = None):
        if events is None:
            events = {}
        self._events = events
    
    def __getattr__(self, name: str) -> Optional[Event]:
        if name == '_events':
            return self._events
        return self._events.get(name) if self._events else None
    
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
    Данные процесса для межпроцессного взаимодействия (Refactored).
    
    Упрощенная версия без зависимостей от старого модуля.
    """
    
    name: str = ""
    status: str = ProcessDataKeys.STATUS_INITIALIZING
    metadata: Dict[str, Any] = field(default_factory=dict)
    custom: Dict[str, Any] = field(default_factory=dict)
    _queues_dict: Dict[str, Queue] = field(default_factory=dict, repr=False)
    _events_dict: Dict[str, Event] = field(default_factory=dict, repr=False)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    
    def __post_init__(self):
        """Инициализация после создания."""
        if self._queues_dict is None:
            self._queues_dict = {}
        if self._events_dict is None:
            self._events_dict = {}
        
        self._queues_proxy = QueuesProxy(self._queues_dict)
        self._events_proxy = EventsProxy(self._events_dict)
    
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
    
    def update_status(self, status: str):
        """Обновляет статус процесса."""
        self.status = status
        self.update_timestamp()
    
    def update_metadata(self, **kwargs):
        """Обновляет метаданные процесса."""
        self.metadata.update(kwargs)
        self.update_timestamp()
    
    def update_custom(self, **kwargs):
        """Обновляет кастомные данные."""
        self.custom.update(kwargs)
        self.update_timestamp()
    
    def to_dict(self) -> Dict[str, Any]:
        """Конвертирует ProcessData в словарь для сериализации."""
        return {
            "name": self.name,
            "status": self.status,
            "metadata": self.metadata.copy(),
            "custom": self.custom.copy(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "queues_count": len(self._queues_dict),
            "events_count": len(self._events_dict),
            "queue_types": list(self._queues_dict.keys()),
            "event_names": list(self._events_dict.keys())
        }

