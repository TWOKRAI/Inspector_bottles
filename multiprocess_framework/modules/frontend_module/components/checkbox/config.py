# -*- coding: utf-8 -*-
"""
CheckboxViewConfig — UI-опции чекбокса (позиция метки, общие поля из BaseControlConfig).
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.frontend_module.components.base.config import (
    BaseControlConfig,
)


class CheckboxViewConfig(BaseControlConfig):
    """
    Настройки отображения чекбокса (позиция метки относительно квадрата).

    Поля ``label`` / ``tooltip`` / ``enabled`` наследуются из ``BaseControlConfig``;
    непустой ``label`` переопределяет подпись из метаданных регистра в ``SchemaTrait``.
    """

    position: Annotated[
        Literal["left", "right", "top", "bottom"],
        FieldMeta("Позиция метки"),
    ] = "left"
