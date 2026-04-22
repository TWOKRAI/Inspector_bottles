# -*- coding: utf-8 -*-
"""
Ядро приложения: базовые виджеты, конфигурация, менеджеры, потоки.
"""
from .base_configurable_widget import ConfigurableWidget
from .app_config import AppConfig, AppConfigManager

__all__ = [
    'ConfigurableWidget',
    'AppConfig',
    'AppConfigManager',
]
