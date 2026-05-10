"""Схемы и конфигурация вкладки «Конструктор»."""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs_setting.tab_item_config import TabItemConfig


def default_tab_item() -> TabItemConfig:
    """Вернуть конфигурацию вкладки «Конструктор» по умолчанию."""
    return TabItemConfig(id="constructor", widget="constructor", title="Конструктор")


__all__ = ["default_tab_item"]
