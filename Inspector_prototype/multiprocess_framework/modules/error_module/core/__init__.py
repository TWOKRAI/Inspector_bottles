# -*- coding: utf-8 -*-
"""Ядро error_module.

``ErrorManager`` импортируйте из ``error_module`` или ``error_module.core.error_manager`` —
не из этого пакета, чтобы избежать циклических импортов при загрузке.
"""

from .error_config_assembly import expand_error_manager_config

__all__ = ["expand_error_manager_config"]
