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

    def select_tree_key(self, key: str) -> None:
        """Выбрать элемент nav-дерева по ключу."""
        ...

    def set_undo_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки Undo."""
        ...

    def set_redo_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки Redo."""
        ...
