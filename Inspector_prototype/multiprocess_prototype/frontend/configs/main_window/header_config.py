# multiprocess_prototype/frontend/configs/main_window/header_config.py
"""
HeaderConfig — приложение-специфичные настройки шапки.

Два варианта:
  - Полноценный: AppHeaderConfig — схема как AdminButtonConfig в framework
  - Сокращённый: get_default_header() — return HeaderConfig(...)

В main_window_config: header=Field(default_factory=AppHeaderConfig) или get_default_header
"""

from typing import List

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema
from multiprocess_framework.refactored.modules.frontend_module.components.header import (
    AdminButtonConfig,
    HeaderButtonItem,
    HeaderConfig,
    LogoConfig,
)


# --- Вариант 1: Полноценный — схема с FieldMeta, как admin_button_widget ---

@register_schema("AppHeaderConfig")
class AppHeaderConfig(SchemaBase):
    """Полноценный конфиг шапки: все поля с дефолтами приложения."""

    logo: LogoConfig = Field(default_factory=lambda: LogoConfig(
        path="resources/logo.png",
        max_width=200,
        max_height=80,
        visible=True,
    ))
    admin_button: AdminButtonConfig = Field(default_factory=lambda: AdminButtonConfig(
        label="Админка",
        visible=True,
    ))
    windows: List[HeaderButtonItem] = Field(default_factory=lambda: [
        HeaderButtonItem(id="main", label="Домой"),
        HeaderButtonItem(id="loading", label="Загрузка"),
    ])


# --- Вариант 2: Сокращённый — только return HeaderConfig(...) ---

def get_default_header() -> HeaderConfig:
    """Сокращённый: переопределяем только нужное."""
    return HeaderConfig(
        logo=LogoConfig(path="resources/logo.png"),
        admin_button=AdminButtonConfig(label="Админка"),
        windows=[
            HeaderButtonItem(id="main", label="Домой"),
            HeaderButtonItem(id="loading", label="Загрузка"),
        ],
    )


__all__ = [
    "HeaderConfig",
    "AppHeaderConfig",
    "HeaderButtonItem",
    "AdminButtonConfig",
    "LogoConfig",
    "get_default_header",
]
