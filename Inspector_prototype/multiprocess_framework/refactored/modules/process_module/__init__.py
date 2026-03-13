"""
Process Module (Refactored) — базовый модуль процессов.

Публичный API:
- ProcessModule — базовый класс процесса
- interfaces — IProcessModule, ISharedResources, IProcessCommunication
- types — ProcessStatus, ManagerType, QueueType, ProcessConfigDict, ProcessStatsDict
- adapters — ProcessAdapter, SchemaAdapter
"""

from .core.process_module import ProcessModule

# Публичные контракты
from .interfaces import IProcessModule, ISharedResources, IProcessCommunication

# Типы
from .types import (
    ProcessStatus,
    ManagerType,
    QueueType,
    ProcessConfigDict,
    ProcessStatsDict,
    ProcessMetadataDict,
)

# Адаптеры
from .adapters import ProcessAdapter, SchemaAdapter

__all__ = [
    # Основной класс
    "ProcessModule",

    # Интерфейсы
    "IProcessModule",
    "ISharedResources",
    "IProcessCommunication",

    # Типы
    "ProcessStatus",
    "ManagerType",
    "QueueType",
    "ProcessConfigDict",
    "ProcessStatsDict",
    "ProcessMetadataDict",

    # Адаптеры
    "ProcessAdapter",
    "SchemaAdapter",
]
