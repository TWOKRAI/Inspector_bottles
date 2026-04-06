"""
Process Module (Refactored) — базовый модуль процессов.

Публичный API:
- ProcessModule — базовый класс процесса
- interfaces — IProcessModule, ISharedResources, IProcessCommunication
- types — ProcessStatus, ManagerType, QueueType, ProcessConfigDict, ProcessStatsDict
- adapters — ProcessAdapter, SchemaAdapter
- ManagersConfig, managers_from_log_dir, managers_payload_for_proc — сборка proc_dict['managers'] (лениво, ADR-114, ADR-115)

ProcessModule и фабрики managers подгружаются лениво (PEP 562), чтобы лёгкий импорт
``from process_module import ProcessPriorityLevel`` не тянул ``ManagersConfig`` / ``ProcessModule``.
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
    if name == "ManagersConfig":
        from .configs.managers_config import ManagersConfig

        return ManagersConfig
    if name == "managers_from_log_dir":
        from .configs.managers_config import managers_from_log_dir

        return managers_from_log_dir
    if name == "managers_payload_for_proc":
        from .configs.managers_config import managers_payload_for_proc

        return managers_payload_for_proc
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Основной класс
    "ProcessModule",
    "ManagersConfig",
    "managers_from_log_dir",
    "managers_payload_for_proc",

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
