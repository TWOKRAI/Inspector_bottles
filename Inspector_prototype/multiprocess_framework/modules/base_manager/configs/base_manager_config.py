# -*- coding: utf-8 -*-
"""BaseManagerConfig — минимальная схема для любого BaseManager."""
from __future__ import annotations

from typing import Annotated

from data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("base_manager")
class BaseManagerConfig(SchemaBase):
    """Базовые поля менеджера (расширяется в модулях-наследниках отдельными схемами)."""

    manager_name: Annotated[str, FieldMeta("Уникальное имя менеджера")] = "BaseManager"
    track_adapters: Annotated[bool, FieldMeta("Учёт адаптеров в диагностике")] = True
