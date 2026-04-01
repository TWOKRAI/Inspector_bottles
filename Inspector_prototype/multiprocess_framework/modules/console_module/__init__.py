"""
console_module — менеджер терминальных окон процесса.

Три уровня использования:
  Уровень 1 (пассивный):  ConsoleConfig(enabled=True) — показать терминал
  Уровень 2 (активный):   console.show() / console.hide() / console.create_console()
  Уровень 3 (God Mode):   ConsoleConfig(interactive=True) — stdin → CommandManager

Публичный API:
    ConsoleManager       — основной класс
    ConsoleConfig        — конфигурация
    IConsoleManager      — интерфейс менеджера
    IPlatformConsole     — интерфейс платформенной реализации
    ConsoleLogChannel    — канал для LoggerManager
    ConsoleRedirector    — перенаправитель stdout/stderr
    ConsoleAdapter       — интегратор с LoggerManager и CommandManager
    ConsoleProcessConfig — конфиг God Mode процесса
"""

from .core.console_manager import ConsoleManager
from .configs import ConsoleConfig, ConsoleProcessConfig
from .interfaces import IConsoleManager, IPlatformConsole
from .channels.console_log_channel import ConsoleLogChannel
from .redirectors.console_redirector import ConsoleRedirector
from .adapters.console_adapter import ConsoleAdapter

__all__ = [
    "ConsoleManager",
    "ConsoleConfig",
    "IConsoleManager",
    "IPlatformConsole",
    "ConsoleLogChannel",
    "ConsoleRedirector",
    "ConsoleAdapter",
    "ConsoleProcessConfig",
]

__version__ = "3.0.0"
