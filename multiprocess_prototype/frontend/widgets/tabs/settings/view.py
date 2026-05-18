# -*- coding: utf-8 -*-
"""SettingsView — Protocol вью для SettingsPresenter.

Расширяет TabViewProtocol: все методы, которые presenter вызывает
на конкретном виджете, не импортируя Qt-классов напрямую.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabViewProtocol


@runtime_checkable
class SettingsView(TabViewProtocol, Protocol):
    """Protocol вью для SettingsPresenter.

    Реализует SettingsTab — presenter работает только через этот интерфейс,
    не зная о конкретных Qt-классах.
    """

    # ------------------------------------------------------------------
    # Стек контента и действий
    # ------------------------------------------------------------------

    def set_content_index(self, index: int) -> None:
        """Переключить content stack на указанный индекс."""
        ...

    def set_action_index(self, index: int) -> None:
        """Переключить action stack на указанный индекс."""
        ...

    def register_action_page(self, key: str, widgets: list) -> int:
        """Создать страницу в action stack с виджетами, вернуть индекс."""
        ...

    def add_content_page(self, key: str, widget: object) -> int:
        """Добавить виджет в content stack, вернуть индекс."""
        ...

    # ------------------------------------------------------------------
    # Навигационное дерево
    # ------------------------------------------------------------------

    def select_tree_key(self, key: str) -> None:
        """Выбрать элемент nav-дерева по ключу."""
        ...

    def build_nav_tree(
        self,
        sections: list[tuple[str, str]],
        admin_children: list[tuple[str, str]],
    ) -> None:
        """Заполнить QTreeWidget секциями и дочерними узлами «Администрация»."""
        ...

    # ------------------------------------------------------------------
    # Фабрики страниц контента (presenter командует, view создаёт Qt-виджеты)
    # ------------------------------------------------------------------

    def add_admin_dashboard_page(self, admin_children: list[tuple[str, str]]) -> None:
        """Создать и зарегистрировать страницу AdminDashboard."""
        ...

    def add_system_settings_page(self) -> None:
        """Создать и зарегистрировать страницу «Настройки системы»."""
        ...

    def add_interface_settings_page(self) -> None:
        """Создать и зарегистрировать страницу «Настройка интерфейса»."""
        ...

    def add_appearance_page(self) -> None:
        """Создать и зарегистрировать страницу «Оформление»."""
        ...

    def add_history_page(self) -> None:
        """Создать и зарегистрировать страницу «История»."""
        ...

    def create_lazy_section(self, key: str) -> None:
        """Создать ленивую секцию (admin-панель) по ключу.

        Вызывается `TreeNavTabPresenter.ensure_lazy_section()` при первой
        активации узла. View создаёт Qt-виджет и вызывает
        `presenter.notify_lazy_section_created(...)` для регистрации индексов.
        """
        ...

    # ------------------------------------------------------------------
    # Undo/Redo
    # ------------------------------------------------------------------

    def set_undo_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки Undo."""
        ...

    def set_redo_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки Redo."""
        ...
