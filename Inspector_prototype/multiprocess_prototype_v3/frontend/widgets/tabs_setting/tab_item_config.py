# multiprocess_prototype_v3/frontend/widgets/tabs_setting/tab_item_config.py
"""
TabItemConfig — описание одной вкладки в TabWidget.

id — уникальный ключ (callback_key, routing). title — текст на табе.
widget — ключ фабрики (tab_factory): recipes, settings, processing, cropped_regions, camera.
"""

from __future__ import annotations

from typing import Annotated

from multiprocess_framework.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("TabItemConfig")
class TabItemConfig(SchemaBase):
    """Одна вкладка: id, заголовок, ключ фабрики виджета."""

    id: Annotated[
        str,
        FieldMeta("ID вкладки", info="Уникальный идентификатор для callback_key и т.д."),
    ] = "recipes"
    title: Annotated[
        str,
        FieldMeta("Заголовок вкладки", info="Текст на табе."),
    ] = "Рецепты"
    widget: Annotated[
        str,
        FieldMeta("Ключ виджета", info="Ключ фабрики вкладок (recipes, settings, …)."),
    ] = "recipes"
