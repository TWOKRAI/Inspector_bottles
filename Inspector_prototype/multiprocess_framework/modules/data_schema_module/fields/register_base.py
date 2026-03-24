# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

RegisterBase перемещён в core/schema_base.py как SchemaBase.
RegisterBase = SchemaBase (алиас для обратной совместимости).

Используйте новый путь:
    from data_schema_module.core import SchemaBase
    from data_schema_module import SchemaBase
"""
from ..core.schema_base import SchemaBase, RegisterBase

__all__ = ["RegisterBase", "SchemaBase"]
