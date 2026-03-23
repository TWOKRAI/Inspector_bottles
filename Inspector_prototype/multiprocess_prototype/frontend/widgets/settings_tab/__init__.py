# multiprocess_prototype/frontend/widgets/settings_tab/
"""
Вкладка настроек: контролы по конфигу (control_v2).

Простой виджет: RegisterBindingContext, coerce_schema_config, IRegistersManagerGui.
При отсутствии rm — заглушка. См. TAB_STRUCTURE.md.

Экспорты:
- SettingsTabWidget — виджет вкладки
- SettingsTabConfig — конфиг (controls, group_title)
- ControlBinding — привязка контрола к регистру
"""

from .schemas import ControlBinding, SettingsTabConfig
from .widget import SettingsTabWidget

__all__ = ["ControlBinding", "SettingsTabConfig", "SettingsTabWidget"]
