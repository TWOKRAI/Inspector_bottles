# -*- coding: utf-8 -*-
"""
Schemas — схемы виджетов и окон (data_schema_module.SchemaBase).

Пакет смешанный (frontend-constructor Ф1, T1.1):
- ``widget_descriptor`` (WidgetDescriptor), ``window_config`` (WindowConfig) —
  LEGACY Gen-1 (frozen 2026-07-18), 0 внешних потребителей.
- ``register_binding`` (RegisterBinding, RegisterFieldMeta, ResolvedMeta) —
  ЖИВОЙ: используется Gen-2 (``components.base.interfaces``,
  ``components.base.traits.schema_trait``,
  ``components.base.infrastructure.{register_adapter,value_transformer}``,
  ``core.base_configurable_widget``). НЕ frozen.

Инвентарь — ``frontend_module/STATUS.md``.
"""

from multiprocess_framework.modules.frontend_module.schemas.widget_descriptor import (
    WidgetDescriptor,
    widget_descriptor_from_dict,
)
from multiprocess_framework.modules.frontend_module.schemas.window_config import WindowConfig
from multiprocess_framework.modules.frontend_module.schemas.register_binding import (
    RegisterBinding,
    RegisterFieldMeta,
    ResolvedMeta,
)

__all__ = [
    "WidgetDescriptor",
    "widget_descriptor_from_dict",
    "WindowConfig",
    "RegisterBinding",
    "RegisterFieldMeta",
    "ResolvedMeta",
]
