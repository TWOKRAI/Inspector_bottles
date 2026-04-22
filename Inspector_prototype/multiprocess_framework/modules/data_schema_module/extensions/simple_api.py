# -*- coding: utf-8 -*-
"""
Simple API — удобные функции для работы со схемами.

Не импортируется автоматически в основном __init__.py.

Использование:
    from data_schema_module.extensions.simple_api import create_config, auto_config
"""
from ..api.simple_api import create_config, create_manager_config, get_config, config_from_dict, auto_config

__all__ = [
    "create_config",
    "create_manager_config",
    "get_config",
    "config_from_dict",
    "auto_config",
]
