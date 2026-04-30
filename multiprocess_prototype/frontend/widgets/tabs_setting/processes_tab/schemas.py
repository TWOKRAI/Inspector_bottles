"""Схемы и конфигурация вкладки «Процессы»."""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs_setting.tab_item_config import TabItemConfig


def default_tab_item() -> TabItemConfig:
    """Вернуть конфигурацию вкладки «Процессы» по умолчанию."""
    return TabItemConfig(id="processes", widget="processes", title="Процессы")


__all__ = ["default_tab_item"]
