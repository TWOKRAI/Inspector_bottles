# multiprocess_prototype/frontend/widgets/settings_tab/settings_nav_panel.py
"""Навигационная панель вкладки «Настройки» — список секций."""

from __future__ import annotations

from multiprocess_framework.modules.frontend_module.core.qt_imports import QWidget

from ...base.navigation_panel_base import NavigationPanelBase


class SettingsNavigationPanel(NavigationPanelBase):
    """Список секций настроек: наследует общий стиль из NavigationPanelBase."""

    SECTIONS = ["Администрация", "Настройки системы", "Настройка интерфейса", "Оформление", "История"]
    DEFAULT_INDEX = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        for section in self.SECTIONS:
            self._add_item(section)
        self._set_current_row(self.DEFAULT_INDEX)
