"""
Process Module (Refactored) — базовый модуль процессов.

Публичный API:
- ProcessModule — базовый класс процесса
- interfaces — IProcessModule, ISharedResources, IProcessCommunication
- types — ProcessStatus, ManagerType, QueueType, ProcessConfigDict, ProcessStatsDict
- adapters — ProcessAdapter, SchemaAdapter

ProcessModule подгружается лениво (PEP 562), чтобы импорт подмодулей вроде
``process_module.configs.managers_config`` не тянул тяжёлую цепочку до
``ProcessModule`` (консольный процессный конфиг и др.).
"""

from typing import Any

# Публичные контракты
from .interfaces import IProcessModule, ISharedResources, IProcessCommunication

# Типы
from .types import (
    ProcessPriorityLevel,
    ProcessStatus,
    ManagerType,
    QueueType,
    ProcessConfigDict,
    ProcessStatsDict,
    ProcessMetadataDict,
)

# Адаптеры
from .adapters import ProcessAdapter, SchemaAdapter


def __getattr__(name: str) -> Any:
    if name == "ProcessModule":
        from .core.process_module import ProcessModule

        return ProcessModule
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Основной класс
    "ProcessModule",

    # Интерфейсы
    "IProcessModule",
    "ISharedResources",
    "IProcessCommunication",

    # Типы
    "ProcessPriorityLevel",
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
