# -*- coding: utf-8 -*-
"""
Frontend Module — модуль UI-фреймворка.

Предоставляет систему виджетов-конструктор:
- Базовые компоненты (слайдеры, чекбоксы, таблицы)
- Доменные виджеты (сборка компонентов + привязка к регистрам)
- Окна верхнего уровня
- Реестры виджетов и окон

Использует data_schema_module и config_module для схем и конфигов.
Регистры — из shared_registers (общие для backend и frontend).
"""

from frontend_module.core.base_configurable_widget import BaseConfigurableWidget
from frontend_module.core.default_factories import create_default_registry
from frontend_module.core.widget_registry import WidgetRegistry
from frontend_module.core.window_registry import WindowRegistry, WindowEntry
from frontend_module.core.registers_bridge import FrontendRegistersBridge
from frontend_module.schemas.widget_descriptor import WidgetDescriptor, widget_descriptor_from_dict
from frontend_module.schemas.window_config import WindowConfig
from frontend_module.core.layout_composer import compose_layout

__all__ = [
    "BaseConfigurableWidget",
    "WidgetRegistry",
    "WindowRegistry",
    "WindowEntry",
    "FrontendRegistersBridge",
    "WidgetDescriptor",
    "widget_descriptor_from_dict",
    "create_default_registry",
    "WindowConfig",
    "compose_layout",
]

from frontend_module.application import (
    FrontendManager,
    ThreadManager,
    WindowManager,
)
__all__.extend(["FrontendManager", "ThreadManager", "WindowManager"])

__version__ = "0.2.0"
