# multiprocess_prototype_v3/frontend/widgets/tabs_setting/tabs_config.py
"""
TabsConfig — список вкладок главного окна (композиция TabItemConfig).

Собирает вкладки из default_tab_item() каждой фичи. Порядок _default_tabs:
Рецепты → Настройки → Обработка → Регионы обрезки → Камера (можно менять).
"""

from __future__ import annotations

from typing import List

from pydantic import Field

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema

from .tab_item_config import TabItemConfig


def _default_tabs() -> List[TabItemConfig]:
    """Вкладки из feature-пакетов: recipes, settings, processing, post_processing, cropped_regions, camera, display."""
    from .camera_tab.schemas import default_tab_item as _cam
    from .post_processing_tab.schemas import default_tab_item as _post
    from .processing_tab.schemas import default_tab_item as _proc
    from .recipes_settings_tab.schemas import default_tab_item as _set
    from ..cropped_regions_widget.schemas import default_tab_item as _crop
    from ..settings_recipe_widget.schemas import default_tab_item as _rec
    from .display_tab.schemas import default_tab_item as _disp

    return [_rec(), _set(), _proc(), _post(), _crop(), _cam(), _disp()]


@register_schema("TabsConfig")
class TabsConfig(SchemaBase):
    """Конфигурация списка вкладок MainWindow."""

    tabs: List[TabItemConfig] = Field(default_factory=_default_tabs)

    def to_tabs_dict_list(self) -> List[dict]:
        """Список dict для границы процесса / сериализации."""
        return [t.model_dump() for t in self.tabs]
