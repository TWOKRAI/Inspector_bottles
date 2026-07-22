"""
ProcessData — runtime-состояние процесса для межпроцессного взаимодействия.

Хранит только runtime-данные: статус, очереди, события, метаданные.
Конфиги процессов хранятся отдельно в ConfigStore (ADR-017).

Queue и Event из multiprocessing pickle-safe нативно.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from multiprocessing import Queue, Event

from ..types import ProcessStatus, ProcessDataDict


class ProcessDataKeys:
    """Константы ключей для наглядного доступа к данным ProcessData."""

    # Ключи для custom (только пользовательские runtime-данные)
    CONSOLE_QUEUE = "console_queue"
    CONSOLE_QUEUES = "console_queues"
    CONSOLE_INFO = "console_info"

    # Ключи для metadata
    METADATA_PRIORITY = "priority"
    METADATA_CLASS_PATH = "class_path"
    METADATA_PID = "pid"
    METADATA_START_TIME = "start_time"

    # Стандартные имена очередей
    QUEUE_SYSTEM = "system"
    QUEUE_DATA = "data"
    QUEUE_STATE = "state"  # FW_STATE_QUEUE: state.changed отдельно от system (drop_oldest)
    QUEUE_COMMANDS = "commands"
    QUEUE_RESULTS = "results"

    # Стандартные имена событий
    EVENT_STOP = "stop"
    EVENT_PAUSE = "pause"
    EVENT_RESUME = "resume"


class QueuesProxy:
    """Прокси для удобного доступа к очередям через атрибуты."""

    __slots__ = ("_queues",)

    def __init__(self, queues: Optional[Dict[str, Queue]] = None) -> None:
        self._queues: Dict[str, Queue] = queues if queues is not None else {}

    def __getattr__(self, name: str) -> Optional[Queue]:
        return self._queues.get(name)

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

    def __getstate__(self):
        return {"_queues": self._queues}

    def __setstate__(self, state: dict) -> None:
        self._queues = state.get("_queues", {})


class EventsProxy:
    """Прокси для удобного доступа к событиям через атрибуты."""

    __slots__ = ("_events",)

    def __init__(self, events: Optional[Dict[str, Event]] = None) -> None:
        self._events: Dict[str, Event] = events if events is not None else {}

    def __getattr__(self, name: str) -> Optional[Event]:
        return self._events.get(name)

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

    def __getstate__(self):
        return {"_events": self._events}

    def __setstate__(self, state: dict) -> None:
        self._events = state.get("_events", {})


@dataclass
class ProcessData:
    """
    Runtime-состояние процесса.

    Содержит только динамические данные: статус, очереди, события, метаданные.
    Конфиги процессов хранятся в ConfigStore — ADR-017.

    Pickle-safe: Queue и Event нативно pickle-able через OS pipes/semaphores.
    """

    name: str = ""
    status: ProcessStatus = ProcessStatus.INITIALIZING
    metadata: Dict[str, Any] = field(default_factory=dict)
    custom: Dict[str, Any] = field(default_factory=dict)
    _queues_dict: Dict[str, Queue] = field(default_factory=dict, repr=False)
    _events_dict: Dict[str, Event] = field(default_factory=dict, repr=False)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self._queues_dict is None:
            self._queues_dict = {}
        if self._events_dict is None:
            self._events_dict = {}
        self._queues_proxy = QueuesProxy(self._queues_dict)
        self._events_proxy = EventsProxy(self._events_dict)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def queues(self) -> QueuesProxy:
        return self._queues_proxy

    @property
    def events(self) -> EventsProxy:
        return self._events_proxy

    # ------------------------------------------------------------------
    # Мутаторы
    # ------------------------------------------------------------------

    def update_timestamp(self) -> None:
        self.updated_at = time.time()

    def add_queue(self, queue_type: str, queue: Queue) -> None:
        self._queues_dict[queue_type] = queue
        self.update_timestamp()

    def clear_queues(self) -> None:
        """Очистить словарь очередей IN-PLACE (routing-epoch, Ф3.1).

        Мутирует ``_queues_dict`` на месте (``clear()``), а НЕ заменяет ссылку:
        ``QueuesProxy`` держит ссылку на этот же dict, поэтому после очистки все
        обращения через ``.queues`` видят пустой набор. Так выживший после switch
        ребёнок роняет ссылки на пересозданные соседом очереди — следующий send
        по этому имени не найдёт очередь и упадёт в hub-relay (Ф1.7), а не в
        осиротевшую мёртвую очередь (тихая потеря). Сами Queue-объекты не
        закрываются: их владелец — пересоздавший сосед, здесь лишь снимается
        локальная стейл-ссылка.
        """
        self._queues_dict.clear()
        self.update_timestamp()

    def add_event(self, event_name: str, event: Event) -> None:
        self._events_dict[event_name] = event
        self.update_timestamp()

    def get_queue(self, queue_type: str) -> Optional[Queue]:
        return self._queues_dict.get(queue_type)

    def get_event(self, event_name: str) -> Optional[Event]:
        return self._events_dict.get(event_name)

    def update_status(self, status: ProcessStatus) -> None:
        self.status = status
        self.update_timestamp()

    def update_metadata(self, **kwargs: Any) -> None:
        self.metadata.update(kwargs)
        self.update_timestamp()

    def update_custom(self, **kwargs: Any) -> None:
        self.custom.update(kwargs)
        self.update_timestamp()

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    def to_dict(self) -> ProcessDataDict:
        """Конвертировать в Dict at Boundary (без Queue/Event ссылок)."""
        # Исключить non-picklable объекты из custom (Event, Manager и т.д.)
        custom_safe = {
            k: v
            for k, v in self.custom.items()
            if k not in ("stop_event", "error_manager", "pause_event")
            and isinstance(v, (str, int, float, bool, type(None), dict, list))
        }
        return ProcessDataDict(
            name=self.name,
            status=self.status.value if isinstance(self.status, ProcessStatus) else str(self.status),
            metadata=self.metadata.copy(),
            custom=custom_safe,
            queue_types=list(self._queues_dict.keys()),
            event_names=list(self._events_dict.keys()),
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    # ------------------------------------------------------------------
    # Pickle
    # ------------------------------------------------------------------

    def __getstate__(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "metadata": self.metadata,
            "custom": self.custom,
            "_queues_dict": self._queues_dict,
            "_events_dict": self._events_dict,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        if "_queues_dict" not in self.__dict__:
            self._queues_dict = {}
        if "_events_dict" not in self.__dict__:
            self._events_dict = {}
        # Нормализуем статус
        if isinstance(self.status, str):
            try:
                self.status = ProcessStatus(self.status)
            except ValueError:
                self.status = ProcessStatus.INITIALIZING
        self._queues_proxy = QueuesProxy(self._queues_dict)
        self._events_proxy = EventsProxy(self._events_dict)
