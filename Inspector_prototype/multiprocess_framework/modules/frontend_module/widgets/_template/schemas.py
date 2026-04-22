# -*- coding: utf-8 -*-
"""
UI-конфигурация виджета.

TODO: заменить TemplateUiConfig на имя своего виджета.
TODO: добавить поля конфигурации (show_advanced, section_visible и т.п.).

Если используется coerce_schema_config — наследовать SchemaBase (Pydantic):
    from data_schema_module import SchemaBase
    class MyUiConfig(SchemaBase): ...

Для простых случаев достаточно dataclass.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class TemplateUiConfig:
    """
    UI-конфигурация виджета.

    TODO: добавить поля для настройки отображения.

    Attributes:
        touch_keyboard: Конфигурация экранной клавиатуры (None — без клавиатуры).
    """

    touch_keyboard: Optional[dict[str, Any]] = None
