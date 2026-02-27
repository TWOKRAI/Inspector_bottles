"""
Command Module (Refactored) - Модуль управления командами.

Предоставляет систему управления командами с интеграцией BaseManager и ObservableMixin.
"""

from .core.base_command_manager import BaseCommandManager
from .core.command_manager import CommandManager
from .adapters.command_adapter import CommandAdapter

# Импорт интерфейса отложен для избежания циклических зависимостей
try:
    from .interfaces import ICommandManager
except ImportError:
    ICommandManager = None

__all__ = [
    # Базовые классы
    "BaseCommandManager",
    # Основные классы
    "CommandManager",
    # Адаптеры
    "CommandAdapter",
    # Интерфейсы
    "ICommandManager",
]

