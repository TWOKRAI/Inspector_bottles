"""
Frontend Module — модуль UI-фреймворка.

Предоставляет систему виджетов-конструктор:
- Базовые компоненты (слайдеры, чекбоксы, таблицы)
- Доменные виджеты (сборка компонентов + привязка к регистрам)
- Окна верхнего уровня

Использует data_schema_module и config_module для схем и конфигов.
Конкретные классы регистров задаёт приложение (наследники SchemaBase);
см. multiprocess_prototype/registers/schemas.

Остальные символы доступны через подпакеты:
- frontend_module.core (qt_imports, WidgetRegistry, WindowRegistry, FrontendRegistersBridge, ...)
- frontend_module.components (SliderControl, CheckboxControl, NumericControl, ...)
- frontend_module.widgets (BaseWidget, HeaderWidget, TabWidget, ImagePanelWidget, ...)
- frontend_module.schemas (WidgetDescriptor, WindowConfig, ...)
- frontend_module.configs (FrontendManagerConfig, WindowManagerConfig, ...)
"""

from multiprocess_framework.modules.frontend_module.application import (
    FrontendLaunchHooks,
    FrontendManager,
    RoutedCommandSender,
    WindowManager,
    run_process_attached_frontend,
)

__all__ = [
    "FrontendManager",
    "FrontendLaunchHooks",
    "RoutedCommandSender",
    "WindowManager",
    "run_process_attached_frontend",
]

__version__ = "0.3.0"
