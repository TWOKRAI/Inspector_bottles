"""
console_module.commands -- обработчики консольных команд.

RegisterCommandHandler -- интерактивная работа с регистрами (reg list/get/set/info).
SystemCommandHandler   -- системные команды диагностики (help/status/ps/stats).
"""

from .register_commands import RegisterCommandHandler
from .system_commands import SystemCommandHandler

__all__ = [
    "RegisterCommandHandler",
    "SystemCommandHandler",
]
