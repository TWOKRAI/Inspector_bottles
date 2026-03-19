# multiprocess_prototype/frontend/configs/tabs/tabs_config.py
"""
TabsConfig — конфигурация вкладок TabWidget.

Список TabItemConfig. Виджеты создаются через WIDGET_REGISTRY по ключу widget.
"""

from typing import List

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema

from .tab_item_config import TabItemConfig


def _default_tabs() -> List[TabItemConfig]:
    return [
        TabItemConfig(id="recipes", title="Рецепты", widget="recipes"),
        TabItemConfig(id="settings", title="Настройки", widget="settings"),
        TabItemConfig(id="processing", title="Обработка", widget="processing"),
        TabItemConfig(id="camera", title="Камера", widget="camera"),
    ]


@register_schema("TabsConfig")
class TabsConfig(SchemaBase):
    """Конфигурация списка вкладок."""

    tabs: List[TabItemConfig] = Field(default_factory=_default_tabs)

    def to_tabs_dict_list(self) -> List[dict]:
        """Список dict для MainWindow."""
        return [t.model_dump() for t in self.tabs]
