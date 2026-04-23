"""
process_module — типы и перечисления.

Все публичные типы модуля. Не импортирует из других модулей фреймворка.
"""

from enum import Enum
from typing import Any, TypedDict


class ProcessPriorityLevel(str, Enum):
    """Уровни приоритета процесса ОС (для proc_dict.priority)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"  # для будущего расширения


class ProcessStatus(str, Enum):
    """Статусы жизненного цикла процесса."""

    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    CRASHED = "crashed"
    UNRESPONSIVE = "unresponsive"
    FAILED = "failed"


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
