"""
Фабрика платформенной консоли.

Использование:
    from .platforms import create_platform_console
    platform = create_platform_console()
"""
import sys

from .base import IPlatformConsole


def create_platform_console() -> IPlatformConsole:
    """Создать экземпляр платформо-зависимой консоли."""
    if sys.platform == "win32":
        from .windows import WindowsConsole
        return WindowsConsole()
    else:
        from .unix import UnixConsole
        return UnixConsole()


__all__ = ["IPlatformConsole", "create_platform_console"]
