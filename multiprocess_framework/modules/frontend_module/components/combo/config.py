# -*- coding: utf-8 -*-
"""
ComboViewConfig — UI-опции выпадающего списка (ComboControl).
"""

from __future__ import annotations

from typing import Annotated, List, Optional

from multiprocess_framework.modules.data_schema_module import FieldMeta
from multiprocess_framework.modules.frontend_module.components.base.config import BaseControlConfig


class ComboViewConfig(BaseControlConfig):
    """
    Настройки отображения ComboBox.

    Поля ``label`` / ``tooltip`` / ``enabled`` наследуются из ``BaseControlConfig``.
    ``items`` — если указаны, используются вместо items из типа поля (Literal args).
    ``placeholder`` — текст при пустом выборе (вставляется как первый пустой item).
    """

    items: Annotated[
        Optional[List[str]],
        FieldMeta("Явный список items (переопределяет Literal args)"),
    ] = None
    placeholder: Annotated[
        str,
        FieldMeta("Текст пустого выбора"),
    ] = ""
