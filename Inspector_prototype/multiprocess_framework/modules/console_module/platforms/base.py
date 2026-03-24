"""
IPlatformConsole — платформо-зависимый интерфейс терминала.

Re-export из interfaces.py для удобства импорта внутри platforms/.
"""
from ..interfaces import IPlatformConsole

__all__ = ["IPlatformConsole"]
