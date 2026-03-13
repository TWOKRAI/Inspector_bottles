# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

RegisterMixin перемещён в core/schema_mixin.py как SchemaMixin.
RegisterMixin = SchemaMixin (алиас для обратной совместимости).

Используйте новый путь:
    from data_schema_module.core import SchemaMixin
    from data_schema_module import SchemaMixin
"""
from ..core.schema_mixin import SchemaMixin, RegisterMixin, _ALL_FIELDS_META_CACHE, _FIELD_META_CACHE

__all__ = ["RegisterMixin", "SchemaMixin", "_ALL_FIELDS_META_CACHE", "_FIELD_META_CACHE"]
