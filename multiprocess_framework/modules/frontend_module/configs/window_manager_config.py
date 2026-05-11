# -*- coding: utf-8 -*-
"""WindowManagerConfig — схема параметров WindowManager."""
from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.frontend_module.schema_adapter import FieldMeta, SchemaBase, register_schema


@register_schema("frontend_window_manager")
class WindowManagerConfig(SchemaBase):
    """Метаданные уровня доступа и поведения окон (без Qt-объектов)."""

    manager_name: Annotated[str, FieldMeta("Логическое имя")] = "WindowManager"
    default_access_level: Annotated[int, FieldMeta("Уровень доступа по умолчанию", min=0, max=10)] = 0
