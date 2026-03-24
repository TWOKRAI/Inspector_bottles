# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

FieldRouting перемещён в core/field_routing.py.

Используйте новый путь:
    from data_schema_module.core import FieldRouting
    from data_schema_module import FieldRouting
"""
from ..core.field_routing import FieldRouting

__all__ = ["FieldRouting"]
