# -*- coding: utf-8 -*-
"""
Error Module (Refactored) — специализированный менеджер ошибок.

Наследует LoggerManager. Принимает конфиг как dict (dict at boundary) или
объект с build() -> (name, dict). ErrorManagerConfig — RegisterBase для
единообразия с process configs.
"""

from .core.error_manager import ErrorManager
from .config.error_config import ErrorManagerConfig

__all__ = [
    "ErrorManager",
    "ErrorManagerConfig",
]

__version__ = "1.0.0"
