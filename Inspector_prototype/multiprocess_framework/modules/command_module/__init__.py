"""
Command Module (Refactored) - Модуль управления командами.

Предоставляет систему управления командами с интеграцией BaseManager и ObservableMixin.
"""

from .core.base_command_manager import BaseCommandManager
from .core.command_manager import CommandManager
from .adapters.command_adapter import CommandAdapter
from .interfaces import ICommandManager
from .configs.command_manager_config import CommandManagerConfig

__all__ = [
    # Основной менеджер
    "CommandManager",
    # Адаптер для процессов
    "CommandAdapter",
    # Интерфейсы
    "ICommandManager",
    # Лёгкий менеджер (без ObservableMixin)
    "BaseCommandManager",
    "CommandManagerConfig",
]

