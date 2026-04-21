# -*- coding: utf-8 -*-
"""
Widgets — составной UI фреймворка: вкладки, BaseWidget, шапка, таблицы, клавиатура.

Примитивы контролов (слайдер, чекбокс, …) — пакет ``frontend_module.components``.
"""
from .image_panel import ImagePanelWidget

__all__ = ["ImagePanelWidget"]

_HAS_QT = False
try:
    from frontend_module.core.qt_imports import QWidget  # noqa: F401
    _HAS_QT = True
except ImportError:
    pass

if _HAS_QT:
    from .base_widget import BaseWidget, WidgetSignalBus
    from .tabs import (
        BaseTab,
        MvpTabBase,
        RegisterBindingContext,
        TabPresenterBase,
        TabViewProtocol,
        TabWidget,
        callback_no_args,
        create_registers_placeholder,
        tab_callbacks_from_dict,
        tab_callbacks_to_dict,
    )
    from .header import (
        AdminButtonConfig,
        ButtonHeader,
        HeaderButtonItem,
        HeaderConfig,
        HeaderWidget,
        LogoConfig,
    )
    from .keyboard import VirtualKeyboard
    from .keyboard import VirtualKeyboardMini
    from .keyboard import bind_touch_keyboard_line_edit, merge_touch_keyboard_dicts
    from .tables import (
        StructuredTableWidget,
        StructuredTwoLevelTreeWidget,
        TableWithToolbar,
        TwoLevelTreeWithToolbar,
    )
    from .performance_monitor import PerformanceMonitor

    __all__.extend(
        [
            "BaseWidget",
            "WidgetSignalBus",
            "BaseTab",
            "MvpTabBase",
            "RegisterBindingContext",
            "TabPresenterBase",
            "TabViewProtocol",
            "TabWidget",
            "callback_no_args",
            "create_registers_placeholder",
            "tab_callbacks_from_dict",
            "tab_callbacks_to_dict",
            "HeaderWidget",
            "ButtonHeader",
            "HeaderConfig",
            "LogoConfig",
            "AdminButtonConfig",
            "HeaderButtonItem",
            "VirtualKeyboard",
            "VirtualKeyboardMini",
            "merge_touch_keyboard_dicts",
            "bind_touch_keyboard_line_edit",
            "StructuredTableWidget",
            "StructuredTwoLevelTreeWidget",
            "TableWithToolbar",
            "TwoLevelTreeWithToolbar",
            "PerformanceMonitor",
        ]
    )
