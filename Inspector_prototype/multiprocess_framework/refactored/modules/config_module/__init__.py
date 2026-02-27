"""
Config Module (Refactored) - Модуль управления конфигурациями.

Предоставляет систему управления конфигурациями с интеграцией:
- BaseManager для единообразия со всеми менеджерами
- data_schema_module для валидации и конвертации
- shared_resources_module для межпроцессного хранения
"""

from .core.base_config import Config
from .core.config_manager import ConfigManager
from .sections.config_section import ConfigSection
from .interfaces import IConfigManager, IConfig

__all__ = [
    # Основные классы
    "Config",
    "ConfigManager",
    "ConfigSection",
    # Интерфейсы
    "IConfigManager",
    "IConfig",
]

# Для обратной совместимости (если нужно)
__version__ = "2.0.0"

