"""
process_module — типы и перечисления.

Все публичные типы модуля.
ProcessStatus — re-export из base_manager (единый enum, ADR-117).
"""

from enum import Enum
from typing import Any, TypedDict

# Единый ProcessStatus из base_manager (ADR-117).
# Сохранён как re-export для backward compat.
from ...base_manager.types.process_status import ProcessStatus


class ProcessPriorityLevel(str, Enum):
    """Уровни приоритета процесса ОС (для proc_dict.priority)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"  # для будущего расширения


class ManagerType(str, Enum):
    """Типы менеджеров внутри процесса."""

    WORKER = "worker"
    LOGGER = "logger"
    COMMAND = "command"
    ROUTER = "router"


class QueueType(str, Enum):
    """Стандартные типы очередей процесса."""

    SYSTEM = "system"
    DATA = "data"
    BROADCAST = "broadcast"
    COMMANDS = "commands"
    RESULTS = "results"
    CUSTOM = "custom"


class ProcessConfigDict(TypedDict, total=False):
    """Конфигурация процесса (Dict at Boundary)."""

    process: dict[str, Any]
    managers: dict[str, Any]
    modules: dict[str, Any]
    workers: dict[str, Any]
    custom: dict[str, Any]


class ProcessStatsDict(TypedDict, total=False):
    """Статистика процесса (Dict at Boundary)."""

    name: str
    running: bool
    status: str
    queues: dict[str, Any]
    workers: dict[str, Any]
    managers: dict[str, Any]


class ProcessMetadataDict(TypedDict, total=False):
    """Метаданные процесса."""

    priority: int
    class_path: str
    pid: int
    start_time: float
