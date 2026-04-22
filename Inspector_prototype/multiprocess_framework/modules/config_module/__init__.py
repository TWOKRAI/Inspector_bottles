"""
Config Module — управление конфигурациями в рантайме.

- **configs/** — только SchemaBase-схемы (наследник ``ConfigManagerConfig``).
- **core/** — ``Config`` (контейнер данных одной конфигурации) и ``ConfigManager``.
- **sections/** — представления на часть ``Config``.
- ``shared_resources_module`` — хранение dict между процессами (ConfigStore).
"""

from .core.config import Config
from .core.config_manager import ConfigManager
from .sections.config_section import ConfigSection
from .configs import ConfigManagerConfig
from .interfaces import IConfigManager, IConfig

__all__ = [
    # Основные классы
    "Config",
    "ConfigManager",
    "ConfigManagerConfig",
    "ConfigSection",
    # Интерфейсы
    "IConfigManager",
    "IConfig",
]

# Для обратной совместимости (если нужно)
__version__ = "2.0.0"

