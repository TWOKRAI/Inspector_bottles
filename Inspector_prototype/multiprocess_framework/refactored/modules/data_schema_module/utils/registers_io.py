# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

registers_io функции перемещены в serialization/io.py.

Используйте новый путь:
    from data_schema_module.serialization import registers_to_dict, ...
    from data_schema_module import registers_to_dict, ...
"""
from ..serialization.io import (
    registers_to_dict,
    registers_from_dict,
    registers_to_json,
    registers_from_json,
    registers_to_yaml,
    registers_from_yaml,
    registers_to_flat_dict,
    registers_from_flat_dict,
)

__all__ = [
    "registers_to_dict",
    "registers_from_dict",
    "registers_to_json",
    "registers_from_json",
    "registers_to_yaml",
    "registers_from_yaml",
    "registers_to_flat_dict",
    "registers_from_flat_dict",
]
