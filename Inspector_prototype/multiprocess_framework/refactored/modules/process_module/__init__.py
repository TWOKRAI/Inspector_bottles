"""
Process Module (Refactored) - Модуль процессов на основе BaseManager.

Все процессы наследуются от BaseManager и используют ObservableMixin.
"""

from .core.process_module import ProcessModule

__all__ = [
    'ProcessModule',
]

