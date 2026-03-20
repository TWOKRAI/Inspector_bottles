# multiprocess_prototype/frontend/widgets/tabs/tabs_config.py
"""
TabsConfig — список вкладок главного окна (композиция TabItemConfig).

Собирает вкладки прототипа; отдельные вкладки настраиваются в своих пакетах
(e.g. settings_tab/config.py для содержимого Settings).
"""

from typing import List

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema

from .tab_item_config import TabItemConfig


def _default_tabs() -> List[TabItemConfig]:
    """Собирает вкладки из feature-пакетов (один источник заголовков/id)."""
    from ..camera_tab.config import default_tab_item as _cam
    from ..processing_tab.config import default_tab_item as _proc
    from ..recipes_tab.config import default_tab_item as _rec
    from ..settings_tab.config import default_tab_item as _set

    return [_rec(), _set(), _proc(), _cam()]


@register_schema("TabsConfig")
class TabsConfig(SchemaBase):
    """Конфигурация списка вкладок MainWindow."""

    tabs: List[TabItemConfig] = Field(default_factory=_default_tabs)

    def to_tabs_dict_list(self) -> List[dict]:
        return [t.model_dump() for t in self.tabs]
