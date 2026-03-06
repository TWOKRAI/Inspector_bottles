# -*- coding: utf-8 -*-
"""
Регистры пост-обработки: управление регионами, цепочками обработки и режимом просмотра.
"""
from typing import Annotated, Any, Dict, List, Optional

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
)


class PostProcessingRegisters(RegisterBase):
    """Регистры пост-обработки изображений."""

    enable_post_processing: Annotated[
        bool,
        FieldMeta("Включить пост-обработку", info="Включить этап пост-обработки."),
    ] = False

    # Сложные структуры данных — без FieldMeta, управляются программно
    regions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Список регионов интереса",
    )

    region_chains: Dict[str, Any] = Field(
        default_factory=dict,
        description="Цепочки обработки по регионам",
    )

    view_mode: Annotated[
        str,
        FieldMeta(
            "Режим просмотра",
            info="Режим отображения: 'main' — основное изображение, "
                 "'region' — выбранный регион, 'list' — список регионов.",
        ),
    ] = "main"

    selected_region: Annotated[
        Optional[str],
        FieldMeta("Выбранный регион", info="Имя активного региона для просмотра."),
    ] = None

    show_region_processed: Annotated[
        bool,
        FieldMeta("Показать обработанный регион", info="Отобразить результат обработки выбранного региона."),
    ] = False
