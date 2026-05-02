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
        ProcessMonitor           — мониторинг состояний

    Адаптеры:
        ProcessSchemaAdapter     — SchemaBase → dict для SystemLauncher

    ADR-117 (2026-04-25, обновлено 2026-05-02): ProcessStatus enum живёт в
    base_manager (импорт через `from multiprocess_framework import ProcessStatus`).
    Локальный алиас `ProcessStatus = ProcessStatusMonitor` удалён в Tier-1
    IMPROVEMENT_PLAN — для класса мониторинга использовать ProcessStatusMonitor.
"""

from .interfaces import ISystemLauncher, IProcessManagerProcess, IProcessRegistry
from .process.process_manager_process import ProcessManagerProcess
from .launcher import SystemLauncher, ProcessSpawner
from .core import ProcessRegistry, ProcessPriority, ProcessStatusMonitor
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
    "ProcessStatusMonitor",
    "ProcessMonitor",
    # Адаптеры
    "ProcessSchemaAdapter",
]
