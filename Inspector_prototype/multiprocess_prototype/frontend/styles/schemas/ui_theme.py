# multiprocess_prototype/frontend/styles/schemas/ui_theme.py
"""
Тема UI в одном формате с остальными конфигами (SchemaBase).

Сериализация в JSON/YAML для рецептов и версий; на границе процесса — dict
(Dict at Boundary). Подстановка в QSS — через StyleSession; дефолты QSS во ``frontend_module``.
"""
from __future__ import annotations

from typing import Any, Dict

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema


@register_schema("UiThemeConfig")
class UiThemeConfig(SchemaBase):
    """
    Переопределения поверх дефолтов встроенных стилей фреймворка (`default_bundles`).

    - `global_tokens`: плоский словарь, merge в `StyleSession.set_global_tokens`
      (палитра, общие имена в нескольких QSS).
    - `bundle_overrides`: style_id → {token → value}, напр.
      ``{"app_tab_main": {"pane_border": "#444"}}``.

    Полная схема всех возможных ключей намеренно не дублируется в Pydantic —
    ключи совпадают с плейсхолдерами в `.qss`; при необходимости жёсткой типизации
    можно ввести вложенные модели по группам (palette, metrics).
    """

    global_tokens: Dict[str, Any] = Field(default_factory=dict)
    bundle_overrides: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
