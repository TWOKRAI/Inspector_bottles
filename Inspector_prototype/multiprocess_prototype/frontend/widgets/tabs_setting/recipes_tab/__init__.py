# multiprocess_prototype/frontend/widgets/tabs_setting/recipes_tab/
"""
Вкладка рецептов. Заглушка (QLabel), далее — таблица.

Простой виджет: coerce_schema_config, IRegistersManagerGui (пока rm не используется).
См. TAB_STRUCTURE.md.

Экспорты:
- RecipesTabWidget — виджет вкладки
- RecipesTabConfig — конфиг заглушки (stub_caption, stub_label_style)
"""

from .schemas import RecipesTabConfig
from .widget import RecipesTabWidget

__all__ = ["RecipesTabConfig", "RecipesTabWidget"]
