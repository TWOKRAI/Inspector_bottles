# -*- coding: utf-8 -*-
"""
Components — переиспользуемые UI-компоненты.

Структура: base, header, controls, tabs, tables, keyboard.
Реэкспорт для удобного импорта: from frontend_module.components import HeaderWidget, ...
"""
from frontend_module.components.controls import (
    BindingConfig,
    CheckboxConfig,
    CheckboxControl,
    NumericControl,
    NumericViewConfig,
    SliderConfig,
)

__all__ = [
    "BindingConfig",
    "CheckboxConfig",
    "CheckboxControl",
    "NumericControl",
    "NumericViewConfig",
    "SliderConfig",
]

try:
    from frontend_module.components.tables import StructuredTableWidget, TableWithToolbar
    __all__.extend(["StructuredTableWidget", "TableWithToolbar"])
except ImportError:
    StructuredTableWidget = None
    TableWithToolbar = None

try:
    from frontend_module.components.tabs import TabWidget, BaseTab
    __all__.extend(["TabWidget", "BaseTab"])
except ImportError:
    TabWidget = None
    BaseTab = None

try:
    from frontend_module.components.header import HeaderWidget
    from frontend_module.components.base import ButtonHeader
    __all__.extend(["HeaderWidget", "ButtonHeader"])
except ImportError:
    HeaderWidget = None
    ButtonHeader = None

try:
    from frontend_module.components.keyboard import VirtualKeyboard
    __all__.append("VirtualKeyboard")
except ImportError:
    VirtualKeyboard = None

try:
    from frontend_module.components.keyboard import VirtualKeyboardMini
    __all__.append("VirtualKeyboardMini")
except ImportError:
    VirtualKeyboardMini = None

try:
    from frontend_module.components.performance_monitor import PerformanceMonitor
    __all__.append("PerformanceMonitor")
except ImportError:
    PerformanceMonitor = None
