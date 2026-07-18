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

ConsoleProcessConfig (конфиг God Mode процесса) переехал в
``process_module.configs.console_process_config`` (Фаза 2 framework-layer-grouping,
K1) — это артефакт запуска процесса, не собственность консоли.
"""

from .core.console_manager import ConsoleManager
from .configs import ConsoleConfig
from .interfaces import IConsoleManager, IPlatformConsole
from .channels.console_log_channel import ConsoleLogChannel
from .redirectors.console_redirector import ConsoleRedirector
from .adapters.console_adapter import ConsoleAdapter
from .commands import RegisterCommandHandler, SystemCommandHandler

__all__ = [
    "ConsoleManager",
    "ConsoleConfig",
    "IConsoleManager",
    "IPlatformConsole",
    "ConsoleLogChannel",
    "ConsoleRedirector",
    "ConsoleAdapter",
    "RegisterCommandHandler",
    "SystemCommandHandler",
]

__version__ = "3.0.0"
