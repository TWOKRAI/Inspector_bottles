# -*- coding: utf-8 -*-
"""SystemSettingsView — Protocol вью для SystemSettingsPresenter.

Presenter работает через этот интерфейс, не импортируя Qt-классы напрямую.
Конкретная реализация — SystemSection (section.py).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabViewProtocol


@runtime_checkable
class SystemSettingsView(TabViewProtocol, Protocol):
    """Protocol вью для SystemSettingsPresenter.

    Методы вызываются presenter'ом для обновления UI-состояния
    без прямого импорта Qt-классов.
    """

    def set_editor_value(self, key: str, value: object) -> None:
        """Установить значение редактора по ключу 'section.field'."""
        ...

    def get_editor_values(self) -> dict[str, object]:
        """Получить текущие значения всех редакторов {key: value}."""
        ...

    def set_dirty_indicator(self, dirty: bool) -> None:
        """Обновить индикатор несохранённых изменений."""
        ...

    def show_validation_error(self, key: str, message: str) -> None:
        """Подсветить редактор с ошибкой и установить tooltip."""
        ...

    def clear_validation_errors(self) -> None:
        """Снять все подсветки ошибок с редакторов."""
        ...

    def set_save_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки «Сохранить»."""
        ...

    def set_reset_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки «Сбросить»."""
        ...
