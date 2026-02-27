"""
Console Module - Модуль управления консольными окнами.

Простой и мощный модуль для:
- Создания консольных окон для процессов
- Группировки процессов в общие консоли
- Перенаправления stdout/stderr
- Отправки сообщений через Router
- Создания отдельных каналов для специальных сообщений

Использование:
    from ..Console_module import ConsoleManager
    
    # Создание менеджера
    console_manager = ConsoleManager(logger=logger)
    
    # Настройка консоли для процесса
    console_manager.configure_process_console(
        process_name="Alice",
        enabled=True,
        group="workers"  # опционально
    )
    
    # Создание отдельного канала для специальных сообщений
    channel = console_manager.create_custom_channel(
        name="notifications",
        title="System Notifications"
    )
"""

from .console_manager import ConsoleManager
from .console_channel import ConsoleChannel

__all__ = ['ConsoleManager', 'ConsoleChannel']


