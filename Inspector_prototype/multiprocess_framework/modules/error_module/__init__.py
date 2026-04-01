# -*- coding: utf-8 -*-
"""
Error Module (Refactored) — специализированный менеджер ошибок.

Наследует LoggerManager. Принимает конфиг как dict (dict at boundary),
ErrorManagerConfig (SchemaBase) или объект с build() -> (name, dict).
Сборка severity-каналов из плоских полей — в ``expand_error_manager_config``.

``ErrorManager`` подгружается лениво, чтобы ``import error_module`` не тянул
цепочку logger → … → тяжёлые пакеты при простом доступе к схеме/сборке.
"""
from __future__ import annotations

from .configs.error_manager_config import ErrorManagerConfig
from .core.error_config_assembly import expand_error_manager_config


def __getattr__(name: str):
    if name == "ErrorManager":
        from .core.error_manager import ErrorManager

        return ErrorManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ErrorManager",
    "ErrorManagerConfig",
    "expand_error_manager_config",
]

__version__ = "1.0.0"
