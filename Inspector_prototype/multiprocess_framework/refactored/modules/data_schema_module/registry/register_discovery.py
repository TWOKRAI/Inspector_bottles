# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

Функции перемещены в registry/discovery.py.

Используйте новый путь:
    from data_schema_module.registry.discovery import discover_registers_from_package
    from data_schema_module.registry import discover_registers_from_package
"""
from .discovery import (
    discover_registers_from_package,
    register_package_schemas,
    register_package_registers,
    _class_name_to_key,
    _class_name_to_register_name,
)

__all__ = [
    "discover_registers_from_package",
    "register_package_schemas",
    "register_package_registers",
    "_class_name_to_key",
    "_class_name_to_register_name",
]
