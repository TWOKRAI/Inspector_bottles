# -*- coding: utf-8 -*-
"""
AppConfig — конфигурация приложения (Pydantic).
Реэкспорт из settings_schema для совместимости с coordinator и др.
"""
from .settings_schema import AppConfig, get_config, set_config

__all__ = ["AppConfig", "get_config", "set_config"]
