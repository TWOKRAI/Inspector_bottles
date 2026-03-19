# multiprocess_prototype/frontend/configs/tabs/__init__.py
"""Конфигурации вкладок и виджетов."""

from .control_binding import ControlBinding
from .settings_tab_config import SettingsTabConfig
from .tab_item_config import TabItemConfig
from .tabs_config import TabsConfig
from .window_registry_config import _default_window_registry

__all__ = [
    "ControlBinding",
    "SettingsTabConfig",
    "TabItemConfig",
    "TabsConfig",
    "_default_window_registry",
]
