# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

DataValidator перемещён в core/validators.py.

Используйте новый путь:
    from data_schema_module.core import DataValidator
    from data_schema_module import DataValidator
"""
from ..core.validators import DataValidator

__all__ = ["DataValidator"]
