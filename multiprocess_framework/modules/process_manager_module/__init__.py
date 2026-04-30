"""
Process Manager Module (Refactored) — модуль управления процессами.

Публичный API:
    Контракты (interfaces.py):
        ISystemLauncher          — фасад запуска системы
        IProcessManagerProcess   — оркестратор процессов
        IProcessRegistry         — реестр процессов ОС

    Реализации:
        SystemLauncher           — фасад (launcher/system_launcher.py)
        ProcessSpawner           — bootstrap (launcher/spawner.py)
        ProcessManagerProcess    — оркестратор (process/process_manager_process.py)

    Core-компоненты:
        ProcessRegistry          — реестр + lifecycle
        ProcessPriority          — управление приоритетами
        ProcessStatusMonitor     — мониторинг процессов ОС
        ProcessStatus            — алиас ProcessStatusMonitor (backward compat)
        ProcessMonitor           — мониторинг состояний

    Адаптеры:
        ProcessSchemaAdapter     — SchemaBase → dict для SystemLauncher
"""

from .interfaces import ISystemLauncher, IProcessManagerProcess, IProcessRegistry
from .process.process_manager_process import ProcessManagerProcess
from .launcher import SystemLauncher, ProcessSpawner
from .core import ProcessRegistry, ProcessPriority, ProcessStatus, ProcessStatusMonitor
from .monitor import ProcessMonitor
from .adapters.schema_adapter import ProcessSchemaAdapter

__all__ = [
    # Контракты
    "ISystemLauncher",
    "IProcessManagerProcess",
    "IProcessRegistry",
    # Реализации
    "SystemLauncher",
    "ProcessSpawner",
    "ProcessManagerProcess",
    # Core-компоненты
    "ProcessRegistry",
    "ProcessPriority",
    "ProcessStatus",
    "ProcessStatusMonitor",
    "ProcessMonitor",
    # Адаптеры
    "ProcessSchemaAdapter",
]
