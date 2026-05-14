# -*- coding: utf-8 -*-
"""
Schemas — схемы виджетов и окон (data_schema_module.SchemaBase).
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
