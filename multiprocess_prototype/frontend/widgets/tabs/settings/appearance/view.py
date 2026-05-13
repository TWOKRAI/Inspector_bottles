# -*- coding: utf-8 -*-
"""AppearanceView -- Protocol вью для AppearancePresenter.

Presenter работает через этот интерфейс, не импортируя Qt-классы напрямую.
Конкретная реализация -- AppearanceSection (section.py).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabViewProtocol


@runtime_checkable
class AppearanceView(TabViewProtocol, Protocol):
    """Protocol вью для AppearancePresenter.

    Методы вызываются presenter'ом для обновления UI-состояния
    без прямого импорта Qt-классов.
    """

    def set_themes(self, themes: list[tuple[str, str, str]]) -> None:
        """Заполнить таблицу тем: [(name, kind, parent), ...]."""
        ...

    def select_theme_row(self, name: str) -> None:
        """Выбрать строку таблицы тем по имени."""
        ...

    def set_vars(
        self,
        var_names: list[str],
        values: dict[str, str],
        descriptions: dict[str, str],
    ) -> None:
        """Заполнить таблицу переменных списком имён и значениями."""
        ...

    def set_crud_buttons_enabled(
        self, save: bool, rename: bool, delete: bool,
    ) -> None:
        """Установить доступность кнопок CRUD для custom-тем."""
        ...

    def get_input_text(
        self, title: str, label: str, default: str = "",
    ) -> tuple[str, bool]:
        """Показать диалог ввода текста и вернуть (text, ok)."""
        ...

    def update_color_preview(self, var_name: str, value: str) -> None:
        """Обновить превью цвета для переменной в таблице."""
        ...

    def close_color_editor(self) -> None:
        """Закрыть inline color editor (если открыт)."""
        ...

    def collect_table_vars(self) -> dict[str, str]:
        """Собрать текущие значения переменных из таблицы."""
        ...
