# multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/schemas.py
"""Схемы конфигурации для вкладки управления плагинами."""

from multiprocess_prototype.frontend.widgets.tabs_setting.tab_item_config import TabItemConfig


def default_tab_item() -> TabItemConfig:
    """Вернуть дефолтный TabItemConfig для вкладки плагинов."""
    return TabItemConfig(id="plugin_manager", widget="plugin_manager", title="Плагины")
