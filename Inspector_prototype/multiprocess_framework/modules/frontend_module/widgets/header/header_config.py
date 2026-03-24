# -*- coding: utf-8 -*-
"""
HeaderConfig — конфигурация HeaderWidget (framework).

Композиция: LogoConfig, AdminButtonConfig, windows (List[HeaderButtonItem]).
Используется в MainWindowConfig. Dict at Boundary: model_dump() → dict для HeaderWidget.
"""
from __future__ import annotations

from typing import List

from pydantic import Field

from data_schema_module import SchemaBase, register_schema

from .admin_button_widget import AdminButtonConfig
from .header_buttons_widget import HeaderButtonItem
from .logo_widget import LogoConfig


def _default_windows() -> List[HeaderButtonItem]:
    """Дефолтный список окон для шапки."""
    return [
        HeaderButtonItem(id="main", label="button_main"),
    ]


@register_schema("HeaderConfig")
class HeaderConfig(SchemaBase):
    """Конфигурация HeaderWidget. model_dump() → dict для HeaderWidget(config=...)."""

    logo: LogoConfig = Field(default_factory=LogoConfig)
    admin_button: AdminButtonConfig = Field(default_factory=AdminButtonConfig)
    windows: List[HeaderButtonItem] = Field(default_factory=_default_windows)
