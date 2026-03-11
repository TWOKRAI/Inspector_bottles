"""
Process Manager Module (Refactored) - Модуль управления процессами.

ProcessManagerProcess — оркестратор с композицией ProcessRegistry + ProcessPriority + ProcessStatus.
"""

from .process.process_manager_process import ProcessManagerProcess
from .launcher import SystemLauncher, ProcessSpawner

__all__ = [
    'ProcessManagerProcess',
    'SystemLauncher',
    'ProcessSpawner',
]

