# -*- coding: utf-8 -*-
"""
Backward-compatible re-export.

Компоненты перемещены в core/:
    fields/field_meta.py      -> core/field_meta.py
    fields/field_routing.py   -> core/field_routing.py
    fields/field_types.py     -> core/field_types.py
    fields/register_mixin.py  -> core/schema_mixin.py  (RegisterMixin = SchemaMixin)
    fields/register_base.py   -> core/schema_base.py   (RegisterBase = SchemaBase)

Все старые импорты продолжают работать через этот файл.
Используйте новые пути для нового кода:
    from data_schema_module.core import FieldMeta, SchemaBase, ...
"""
from ..core.field_meta import FieldMeta
from ..core.field_routing import FieldRouting
from ..core.schema_mixin import SchemaMixin, RegisterMixin
from ..core.schema_base import SchemaBase, RegisterBase
from ..core.field_types import (
    Percent,
    NormalizedFloat,
    Scale,
    Milliseconds,
    Seconds,
    Pixels,
    ImageScale,
    HsvHue,
    HsvChannel,
    NetworkPort,
    FpsLimit,
)

__all__ = [
    "FieldMeta",
    "FieldRouting",
    "SchemaMixin",
    "RegisterMixin",
    "SchemaBase",
    "RegisterBase",
    "Percent",
    "NormalizedFloat",
    "Scale",
    "Milliseconds",
    "Seconds",
    "Pixels",
    "ImageScale",
    "HsvHue",
    "HsvChannel",
    "NetworkPort",
    "FpsLimit",
]
