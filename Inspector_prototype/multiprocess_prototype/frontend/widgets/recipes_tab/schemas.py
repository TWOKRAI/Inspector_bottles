# multiprocess_prototype/frontend/widgets/recipes_tab/schemas.py
"""
Конфиг вкладки «Рецепты» (заглушка).

stub_caption, stub_label_style — текст и стиль QLabel. default_tab_item — для TabsConfig.
"""

from __future__ import annotations

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema


@register_schema("RecipesTabConfig")
class RecipesTabConfig(SchemaBase):
    """Тексты и стили заглушки."""

    stub_caption: str = "Рецепты"
    stub_label_style: str = "font-size: 18px; color: #555;"


def default_tab_item():
    from ..tabs.tab_item_config import TabItemConfig

    return TabItemConfig(id="recipes", title="Рецепты", widget="recipes")
