# -*- coding: utf-8 -*-
"""
Widgets — составной UI фреймворка: вкладки, BaseWidget, шапка, таблицы, клавиатура.

Примитивы контролов (слайдер, чекбокс, …) — пакет ``frontend_module.components``.
"""
from .image_panel import ImagePanelWidget

__all__ = ["ImagePanelWidget"]

try:
    from .base_widget import BaseWidget, WidgetSignalBus

    __all__.extend(["BaseWidget", "WidgetSignalBus"])
except ImportError:
    BaseWidget = None  # type: ignore[assignment]
    WidgetSignalBus = None  # type: ignore[assignment]

try:
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

    __all__.extend(
        [
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
        ]
    )
except ImportError:
    BaseTab = None  # type: ignore[assignment]
    MvpTabBase = None  # type: ignore[assignment]
    TabWidget = None  # type: ignore[assignment]

try:
    from .header import ButtonHeader, HeaderWidget

    __all__.extend(["HeaderWidget", "ButtonHeader"])
except ImportError:
    HeaderWidget = None  # type: ignore[assignment]
    ButtonHeader = None  # type: ignore[assignment]

try:
    from .keyboard import VirtualKeyboard

    __all__.append("VirtualKeyboard")
except ImportError:
    VirtualKeyboard = None  # type: ignore[assignment]

try:
    from .keyboard import VirtualKeyboardMini

    __all__.append("VirtualKeyboardMini")
except ImportError:
    VirtualKeyboardMini = None  # type: ignore[assignment]

try:
    from .tables import (
        StructuredTableWidget,
        StructuredTwoLevelTreeWidget,
        TableWithToolbar,
        TwoLevelTreeWithToolbar,
    )

    __all__.extend(
        [
            "StructuredTableWidget",
            "StructuredTwoLevelTreeWidget",
            "TableWithToolbar",
            "TwoLevelTreeWithToolbar",
        ]
    )
except ImportError:
    StructuredTableWidget = None  # type: ignore[assignment]
    StructuredTwoLevelTreeWidget = None  # type: ignore[assignment]
    TableWithToolbar = None  # type: ignore[assignment]
    TwoLevelTreeWithToolbar = None  # type: ignore[assignment]

try:
    from .performance_monitor import PerformanceMonitor

    __all__.append("PerformanceMonitor")
except ImportError:
    PerformanceMonitor = None  # type: ignore[assignment]
