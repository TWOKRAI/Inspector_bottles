"""
Process Manager Module (Refactored) - Модуль управления процессами на основе BaseManager.

ProcessManager является Сверхэго в архитектуре "Тройцы создания циклов".
"""

from .core.process_manager_core import ProcessManagerCore
from .process.process_manager_process import ProcessManagerProcess

__all__ = [
    'ProcessManagerCore',
    'ProcessManagerProcess',
]

