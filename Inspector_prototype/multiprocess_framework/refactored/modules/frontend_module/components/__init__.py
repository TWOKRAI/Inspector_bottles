# -*- coding: utf-8 -*-
"""
Components — переиспользуемые UI-компоненты.

SliderControl, CheckboxControl — привязка к RegistersManager через BaseConfigurableWidget.
StructuredTableWidget, TableWithToolbar, TabWidget, HeaderWidget, VirtualKeyboard, VirtualKeyboardMini, PerformanceMonitor.
"""
from frontend_module.components.slider_control import SliderControl
from frontend_module.components.checkbox_control import CheckboxControl

__all__ = [
    "SliderControl",
    "CheckboxControl",
]

try:
    from frontend_module.components.structured_table import StructuredTableWidget
    __all__.append("StructuredTableWidget")
except ImportError:
    StructuredTableWidget = None

try:
    from frontend_module.components.table_with_toolbar import TableWithToolbar
    __all__.append("TableWithToolbar")
except ImportError:
    TableWithToolbar = None

try:
    from frontend_module.components.tab_widget import TabWidget, BaseTab
    __all__.extend(["TabWidget", "BaseTab"])
except ImportError:
    TabWidget = None
    BaseTab = None

try:
    from frontend_module.components.header import HeaderWidget, ButtonHeader
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
    from frontend_module.components.keyboard_mini import VirtualKeyboardMini
    __all__.append("VirtualKeyboardMini")
except ImportError:
    VirtualKeyboardMini = None

try:
    from frontend_module.components.performance_monitor import PerformanceMonitor
    __all__.append("PerformanceMonitor")
except ImportError:
    PerformanceMonitor = None
