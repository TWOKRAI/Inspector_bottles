# -*- coding: utf-8 -*-
"""TabLayoutProtocol --- структурный контракт layout'а вкладки.

Определяет минимальный набор методов, которые ``BaseTreeNavTab`` вызывает
на layout-виджете. ``DiffScrollTabLayout`` (prototype) и любой будущий
``StandardTabLayout`` удовлетворяют этому Protocol без явного наследования
(structural subtyping).

Модуль живёт в framework и **не импортирует** ничего app-specific из
``multiprocess_prototype``. Это позволяет ``BaseTreeNavTab`` оставаться
в framework без обратных зависимостей.

См. ADR-126, Phase 3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from PySide6.QtWidgets import QStackedWidget, QWidget


@runtime_checkable
class TabLayoutProtocol(Protocol):
    """Минимальный контракт layout'а вкладки с tree-навигацией.

    Методы покрывают все операции, которые ``BaseTreeNavTab`` выполняет
    при построении UI:

    * ``set_title`` / ``set_action_widget`` / ``set_nav_widget`` /
      ``set_content_widget`` --- наполнение колонок;
    * ``enable_undo_redo`` --- создание кнопок undo/redo;
    * ``register_inner_scrolls`` --- подключение вложенных scroll areas;
    * ``connect_stack`` --- авто-подписка смены страницы стека на refresh;
    * ``refresh_after_page_change`` --- принудительный пересчёт скролла.
    """

    def set_title(self, text: str) -> None:
        """Задать/обновить заголовок layout'а."""
        ...

    def set_action_widget(self, widget: "QWidget") -> None:
        """Задать содержимое action-колонки."""
        ...

    def set_nav_widget(self, widget: "QWidget") -> None:
        """Задать навигационный виджет."""
        ...

    def set_content_widget(self, widget: "QWidget") -> None:
        """Задать виджет основного контента."""
        ...

    def enable_undo_redo(self, action_bus: object | None) -> None:
        """Создать кнопки undo/redo и привязать к шине."""
        ...

    def register_inner_scrolls(self, widget: "QWidget") -> None:
        """Подключить вложенные QScrollArea к синхронизации."""
        ...

    def connect_stack(self, stack: "QStackedWidget", role: str) -> None:
        """Подписать смену страницы стека на refresh layout'а.

        ``stack`` обязан иметь сигнал ``currentChanged`` --- поэтому
        требуем ``QStackedWidget`` (или совместимый подкласс), а не
        произвольный ``QWidget``.
        """
        ...

    def refresh_after_page_change(self, role: str) -> None:
        """Принудительно пересчитать scroll area после смены страницы."""
        ...
