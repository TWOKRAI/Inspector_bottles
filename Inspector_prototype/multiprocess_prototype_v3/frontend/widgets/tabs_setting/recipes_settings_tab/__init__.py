# multiprocess_prototype_v3/frontend/widgets/tabs_setting/recipes_settings_tab/
"""
Вкладка настроек: таблица app-рецепта (AppRecipePanel), без отдельных слайдеров.

RegisterBindingContext, IRegistersManagerGui; при отсутствии rm — заглушка.

Экспорты:
- SettingsTabWidget — виджет вкладки
- SettingsTabConfig — секция конфига (legacy-поля controls/group_title не рендерятся)
- ControlBinding — схема для совместимости с дампами
"""

from .schemas import ControlBinding, SettingsTabConfig
from .widget import SettingsTabWidget

__all__ = ["ControlBinding", "SettingsTabConfig", "SettingsTabWidget"]
