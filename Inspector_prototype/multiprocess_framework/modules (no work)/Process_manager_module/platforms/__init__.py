"""
Платформо-зависимые адаптеры для управления процессами.

Автоматически определяет платформу и предоставляет соответствующий адаптер.
"""

import sys
from typing import Protocol

from .base import PlatformAdapter, StubPlatformAdapter
from .windows import WindowsPlatform
from .linux import LinuxPlatform


def get_platform_adapter() -> PlatformAdapter:
    platform_name = sys.platform
    
    try:
        if platform_name == "win32":
            from .windows import WindowsPlatform
            return WindowsPlatform()
        elif platform_name.startswith("linux"):
            from .linux import LinuxPlatform
            return LinuxPlatform()
        elif platform_name == "darwin":
            # Для macOS можно вернуть LinuxPlatform или создать свой
            from .linux import LinuxPlatform
            return LinuxPlatform()
        else:
            raise NotImplementedError(f"Platform {platform_name} not supported")
    except ImportError as e:
        # Логируем и возвращаем заглушку
        import warnings
        warnings.warn(f"Failed to import platform adapter: {e}")
        
        return StubPlatformAdapter()  


__all__ = ['PlatformAdapter', 'get_platform_adapter', 'WindowsPlatform', 'LinuxPlatform']

