# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

FieldMeta перемещён в core/field_meta.py.

Используйте новый путь:
    from data_schema_module.core import FieldMeta
    from data_schema_module import FieldMeta
"""
from ..core.field_meta import FieldMeta

__all__ = ["FieldMeta"]
