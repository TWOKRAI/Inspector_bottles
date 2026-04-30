# multiprocess_prototype/frontend/widgets/tabs_setting/tabs_config.py
"""
TabsConfig — список вкладок главного окна (композиция TabItemConfig).

Собирает вкладки из default_tab_item() каждой фичи. Порядок _default_tabs:
Настройки → Рецепты → Процессы → Источники → Pipeline → Дисплей.
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema
from pydantic import Field

from .tab_item_config import TabItemConfig


def _default_tabs() -> list[TabItemConfig]:
    """Вкладки: settings, recipes, processes, sources, pipeline, display."""
    from ..recipes.settings_recipe_widget.schemas import default_tab_item as _rec
    from .display_tab.schemas import default_tab_item as _disp
    from .recipes_settings_tab.schemas import default_tab_item as _set

    def _sources() -> TabItemConfig:
        return TabItemConfig(id="sources", widget="sources", title="Источники")

    def _graph() -> TabItemConfig:
        return TabItemConfig(id="pipeline", widget="pipeline", title="Pipeline")

    def _processes() -> TabItemConfig:
        return TabItemConfig(id="processes", widget="processes", title="Процессы")

    return [_set(), _rec(), _processes(), _sources(), _graph(), _disp()]


@register_schema("TabsConfig")
class TabsConfig(SchemaBase):
    """Конфигурация списка вкладок MainWindow."""

    tabs: list[TabItemConfig] = Field(default_factory=_default_tabs)

    def to_tabs_dict_list(self) -> list[dict]:
        """Список dict для границы процесса / сериализации."""
        return [t.model_dump() for t in self.tabs]
