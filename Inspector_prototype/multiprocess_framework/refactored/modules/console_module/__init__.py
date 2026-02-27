"""
Console Module (Refactored) - Модуль управления консольными окнами.

Предоставляет систему управления консолями с интеграцией:
- BaseManager для единообразия со всеми менеджерами
- CommandManager для обработки команд
- RouterManager для отправки сообщений
- ProcessManager для создания отдельного процесса отладки

Режимы работы:
- Встроенный режим: консоль в процессе (опционально включается/выключается)
- Отдельный процесс: создается через ProcessManager для отладки
"""

from .core.console_manager import ConsoleManager
from .channels.console_channel import ConsoleChannel
from .interfaces import IConsoleManager, IConsoleChannel
from .redirectors.console_redirector import ConsoleRedirector

__all__ = [
    # Основные классы
    "ConsoleManager",
    "ConsoleChannel",
    "ConsoleRedirector",
    # Интерфейсы
    "IConsoleManager",
    "IConsoleChannel",
]

__version__ = "2.0.0"

