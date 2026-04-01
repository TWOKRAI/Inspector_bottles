"""
Рантайм config_module: контейнер данных и менеджер (без SchemaBase-схем).

Схемы — пакет ``config_module.configs``.
"""

from .config import Config
from .config_manager import ConfigManager

__all__ = [
    "Config",
    "ConfigManager",
]

