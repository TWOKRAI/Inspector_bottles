# -*- coding: utf-8 -*-
"""
LabelConfig — настройки отображения подписи.
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.frontend_module.components.base.config import BaseControlConfig


class LabelConfig(BaseControlConfig):
    """Настройки подписи (позиция, видимость). Текст подставляется в setup()."""

    position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"
    visible: Annotated[bool, FieldMeta("Видимость")] = True
