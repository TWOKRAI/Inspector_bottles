"""
Типы и TypedDict для shared_resources_module.

Центральное место для всех enum и typed-контрактов модуля.
ProcessStatus — re-export из base_manager (единый enum, ADR-117).
"""

from enum import Enum
from typing import Any, Dict, List, Optional

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict

# Единый ProcessStatus из base_manager (ADR-117).
# Сохранён как re-export для backward compat.
from ...base_manager.types.process_status import ProcessStatus


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


class MemoryAccessStatus(Enum):
    """Результат валидации доступа к SharedMemory."""
    OK = "ok"
    NO_DATA = "no_data"
    INVALID_INDEX = "invalid_index"
    INDEX_OUT_OF_RANGE = "index_out_of_range"
    HANDLE_MISSING = "handle_missing"
    EXCEEDS_MAX_IMAGES = "exceeds_max_images"
    PARAM_MISSING = "param_missing"


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
