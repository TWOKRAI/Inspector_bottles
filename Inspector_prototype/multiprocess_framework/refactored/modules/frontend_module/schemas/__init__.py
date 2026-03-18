# -*- coding: utf-8 -*-
"""
Schemas — схемы виджетов и окон (data_schema_module.SchemaBase).
"""

from frontend_module.schemas.widget_descriptor import WidgetDescriptor, widget_descriptor_from_dict
from frontend_module.schemas.window_config import WindowConfig

__all__ = ["WidgetDescriptor", "widget_descriptor_from_dict", "WindowConfig"]
