"""
Типы и TypedDict для shared_resources_module.

Центральное место для всех enum и typed-контрактов модуля.
Не импортирует ничего из других модулей — zero-dependency leaf.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict


class ProcessStatus(Enum):
    """Жизненный цикл процесса."""
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class ResourceType(Enum):
    """Типы ресурсов, которыми управляет SRM."""
    QUEUE = "queue"
    EVENT = "event"
    SHARED_MEMORY = "shared_memory"


class EventType(Enum):
    """Системные события SRM."""
    PROCESS_REGISTERED = "process_registered"
    PROCESS_STATE_CHANGED = "process_state_changed"
    PROCESS_UNREGISTERED = "process_unregistered"
    QUEUE_ADDED = "queue_added"
    EVENT_ADDED = "event_added"
    CONFIG_UPDATED = "config_updated"


# ---------------------------------------------------------------------------
# TypedDict — контракты для dict-границ (Dict at Boundary)
# ---------------------------------------------------------------------------

class ProcessDataDict(TypedDict, total=False):
    """Сериализованное представление ProcessData (для Dict at Boundary)."""
    name: str
    status: str
    metadata: Dict[str, Any]
    custom: Dict[str, Any]
    queue_types: List[str]
    event_names: List[str]
    created_at: float
    updated_at: float


class QueueConfigDict(TypedDict, total=False):
    """Конфигурация одной очереди."""
    maxsize: int


class MemoryConfigDict(TypedDict, total=False):
    """Конфигурация блока разделяемой памяти."""
    num_images: int
    image_shape: tuple
    dtype: str
    coll: int
