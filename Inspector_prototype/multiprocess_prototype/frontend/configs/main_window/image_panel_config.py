# multiprocess_prototype/frontend/configs/main_window/image_panel_config.py
"""
ImagePanelConfig — конфигурация панели изображений.

Параметры: slots (список слотов для отображения кадров).
"""

from typing import Annotated, List

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("ImageSlotConfig")
class ImageSlotConfig(SchemaBase):
    """Конфигурация слота изображения в ImagePanel."""

    id: str = "original"
    label: Annotated[
        str,
        FieldMeta("Подпись слота", info="Метка слота в UI."),
    ] = "Original"
    visible_default: Annotated[
        bool,
        FieldMeta("Видим по умолчанию", info="Показывать слот при старте."),
    ] = True


def _default_image_slots() -> List[ImageSlotConfig]:
    return [
        ImageSlotConfig(id="original", label="Original", visible_default=True),
        ImageSlotConfig(id="mask", label="Mask", visible_default=True),
    ]


@register_schema("ImagePanelConfig")
class ImagePanelConfig(SchemaBase):
    """Конфигурация ImagePanelWidget."""

    slots: List[ImageSlotConfig] = Field(default_factory=_default_image_slots)
