# multiprocess_prototype/frontend/configs/tabs/tab_item_config.py
"""
TabItemConfig — конфигурация одной вкладки в TabWidget.

id — уникальный идентификатор, title — заголовок, widget — ключ в реестре виджетов.
"""

from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import FieldMeta, SchemaBase, register_schema


@register_schema("TabItemConfig")
class TabItemConfig(SchemaBase):
    """Описание одной вкладки."""

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
        FieldMeta("Ключ виджета", info="Ключ в WIDGET_REGISTRY для создания виджета."),
    ] = "recipes"
