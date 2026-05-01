# -*- coding: utf-8 -*-
"""
Widgets — составной UI фреймворка: вкладки, BaseWidget, шапка, таблицы, клавиатура.

Примитивы контролов (слайдер, чекбокс, …) — пакет ``frontend_module.components``.

Импорты разделены на группы try/except: base_widget и tabs имеют
взаимную зависимость (circular), поэ��ому их нельзя объединять в один блок.
"""
from .image_panel import ImagePanelWidget

__all__ = ["ImagePanelWidget"]

# --- base_widget (зависит от tabs.tab_widget) ---
try:
    from .base_widget import BaseWidget, WidgetSignalBus

    __all__.extend(["BaseWidget", "WidgetSignalBus"])
except ImportError:
    pass

# --- tabs (mvp_facade зависит от base_widget — circular) ---
try:
    from .tabs import (
        BaseTab,
        MvpTabBase,
        PanelTabBase,
        RegisterBindingContext,
        TabPresenterBase,
        TabViewProtocol,
        TabWidget,
        callback_no_args,
        create_registers_placeholder,
        tab_callbacks_from_dict,
        tab_callbacks_to_dict,
    )

    __all__.extend([
        "BaseTab", "MvpTabBase", "PanelTabBase", "RegisterBindingContext",
        "TabPresenterBase", "TabViewProtocol", "TabWidget",
        "callback_no_args", "create_registers_placeholder",
        "tab_callbacks_from_dict", "tab_callbacks_to_dict",
    ])
except ImportError:
    pass

# --- header ---
try:
    from .header import (
        AdminButtonConfig,
        ButtonHeader,
        HeaderButtonItem,
        HeaderConfig,
        HeaderWidget,
        LogoConfig,
    )

    __all__.extend([
        "HeaderWidget", "ButtonHeader", "HeaderConfig",
        "LogoConfig", "AdminButtonConfig", "HeaderButtonItem",
    ])
except ImportError:
    pass

# --- keyboard ---
try:
    from .keyboard import VirtualKeyboard, VirtualKeyboardMini
    from .keyboard import bind_touch_keyboard_line_edit, merge_touch_keyboard_dicts

    __all__.extend([
        "VirtualKeyboard", "VirtualKeyboardMini",
        "merge_touch_keyboard_dicts", "bind_touch_keyboard_line_edit",
    ])
except ImportError:
    pass

# --- tables ---
try:
    from .tables import (
        StructuredTableWidget,
        StructuredTwoLevelTreeWidget,
        TableWithToolbar,
        TwoLevelTreeWithToolbar,
    )

    __all__.extend([
        "StructuredTableWidget", "StructuredTwoLevelTreeWidget",
        "TableWithToolbar", "TwoLevelTreeWithToolbar",
    ])
except ImportError:
    pass

# --- performance monitor ---
try:
    from .performance_monitor import PerformanceMonitor

    __all__.append("PerformanceMonitor")
except ImportError:
    pass

# --- entity_editor ---
try:
    from . import entity_editor

    __all__.append("entity_editor")
except ImportError:
    pass
