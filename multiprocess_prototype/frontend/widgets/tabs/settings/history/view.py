# -*- coding: utf-8 -*-
"""HistoryView — Protocol вью для HistoryPresenter.

Presenter работает через этот интерфейс, не импортируя Qt-классы напрямую.
Конкретная реализация — HistorySection (section.py).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from multiprocess_framework.modules.frontend_module.widgets.tabs import TabViewProtocol


@runtime_checkable
class HistoryView(TabViewProtocol, Protocol):
    """Protocol вью для HistoryPresenter.

    Методы вызываются presenter'ом для обновления UI-состояния
    без прямого импорта Qt-классов.
    """

    def set_table_data(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Заполнить таблицу истории строками (Время, Вкладка, Параметр, Значение)."""
        ...

    def set_save_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки «Сохранить в файл»."""
        ...

    def set_clear_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки «Очистить историю»."""
        ...

    def scroll_to_bottom(self) -> None:
        """Прокрутить таблицу истории к последней строке."""
        ...

    def get_save_path(self) -> str | None:
        """Показать диалог сохранения файла и вернуть выбранный путь (или None)."""
        ...
