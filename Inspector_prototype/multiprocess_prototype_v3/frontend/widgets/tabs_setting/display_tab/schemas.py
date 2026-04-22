# multiprocess_prototype_v3/frontend/widgets/tabs_setting/display_tab/schemas.py
"""
Схема конфигурации вкладки Display.

Хранит пресет по умолчанию и предоставляет default_tab_item()
для регистрации в TabsConfig._default_tabs().
"""

from __future__ import annotations

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema

from multiprocess_prototype_v3.frontend.widgets.tabs_setting.tab_item_config import TabItemConfig


def default_tab_item() -> TabItemConfig:
    """TabItemConfig вкладки «Display»."""
    return TabItemConfig(id="display", widget="display", title="Display")


@register_schema("DisplayTabConfigV3")
class DisplayTabConfig(SchemaBase):
    """Конфиг вкладки управления display-окнами."""

    # Пресет раскладки по умолчанию: none | single | dual | quad | custom
    default_preset: str = "none"
