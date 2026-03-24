# -*- coding: utf-8 -*-
"""
Строки и подписи UI вкладки «Обработка».

Только фронт: не участвует в register_update. Значения параметров — в
`registers.schemas.processing_tab` (ProcessorRegisters, RendererRegisters).
default_tab_item — для TabsConfig.
"""
from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    SchemaBase,
    register_schema,
)


@register_schema("ProcessingTabUiConfig")
class ProcessingTabUiConfig(SchemaBase):
    """Подписи групп, каналов и чекбоксов вкладки обработки."""

    group_color: Annotated[
        str,
        FieldMeta("Группа BGR", info="Заголовок QGroupBox цветовой детекции."),
    ] = "Цветовая детекция (BGR)"

    group_area: Annotated[str, FieldMeta("Площадь пятна", info="Заголовок группы площади.")] = (
        "Площадь пятна"
    )

    group_display: Annotated[str, FieldMeta("Отображение", info="Заголовок группы рендера.")] = (
        "Отображение"
    )

    channel_b: Annotated[str, FieldMeta("Канал B", info="Подпись слайдера B.")] = "B"
    channel_g: Annotated[str, FieldMeta("Канал G", info="Подпись слайдера G.")] = "G"
    channel_r: Annotated[str, FieldMeta("Канал R", info="Подпись слайдера R.")] = "R"

    color_hint: Annotated[str, FieldMeta("Подсказка диапазонов", info="Текст под слайдерами.")] = (
        "Lower | Upper"
    )

    label_min_area_prefix: Annotated[str, FieldMeta("Префикс мин. площади")] = "Мин:"
    label_max_area_prefix: Annotated[str, FieldMeta("Префикс макс. площади")] = "Макс:"
    label_max_area_unlimited: Annotated[
        str,
        FieldMeta("Суффикс при неограниченной площади", info="При max_area == 0."),
    ] = " (без огр.)"
    label_max_area_initial_suffix: Annotated[
        str,
        FieldMeta("Суффикс подсказки для макс. площади"),
    ] = " (0=без огр.)"

    label_px: Annotated[str, FieldMeta("Единица px")] = "px"

    checkbox_original: Annotated[str, FieldMeta("Чекбокс Original")] = "Original"
    checkbox_mask: Annotated[str, FieldMeta("Чекбокс Mask")] = "Mask"
    checkbox_contours: Annotated[str, FieldMeta("Чекбокс Contours")] = "Contours"
    checkbox_bbox: Annotated[str, FieldMeta("Чекбокс BBox")] = "BBox"
    checkbox_save_frames: Annotated[str, FieldMeta("Чекбокс Save frames")] = "Save"


def default_tab_item():
    from ..tab_item_config import TabItemConfig

    return TabItemConfig(id="processing", title="Обработка", widget="processing")
