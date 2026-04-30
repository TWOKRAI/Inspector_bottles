# -*- coding: utf-8 -*-
"""Ядро error_module.

``ErrorManager`` доступен из ``error_module`` (лениво) и из ``error_module.core``
(лениво через ``__getattr__``), чтобы импорт ``expand_error_manager_config`` не
тянул ``logger_module`` до первого обращения к ``ErrorManager``.
"""

from __future__ import annotations

from typing import Any

from .error_config_assembly import expand_error_manager_config

__all__ = ["expand_error_manager_config", "ErrorManager"]


def __getattr__(name: str) -> Any:
    if name == "ErrorManager":
        from .error_manager import ErrorManager

        return ErrorManager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
