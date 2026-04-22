"""
Config Toolbox — опциональные утилиты для работы с конфигами.

Каждый инструмент самостоятельный. Используй что нужно::

    from config_module.tools import deep_merge, multi_merge
    from config_module.tools import ConfigLoader
    from config_module.tools import ConfigFileWatcher  # требует watchdog
"""
from .merge import deep_merge, multi_merge
from .loader import ConfigLoader

# watchdog — опциональная зависимость
try:
    from .watcher import ConfigFileWatcher
except ImportError:
    pass

__all__ = ["deep_merge", "multi_merge", "ConfigLoader", "ConfigFileWatcher"]
