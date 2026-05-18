# -*- coding: utf-8 -*-
"""BaseListNavTab --- динамический CRUD-список в nav-колонке.

Подкласс ``BaseColumnarTab`` для вкладок с динамическим списком элементов
(рецепты, процессы, и т.п.) вместо статического дерева ``SectionSpec``.

Presenter вызывает ``add_item / remove_item / rename_item`` напрямую.
Подкласс переопределяет ``_create_item_widget(key)`` для создания
content-виджетов.

Сигналы:

* ``item_selected(str)``  --- ключ выбранного элемента.
* ``item_added(str)``     --- ключ добавленного элемента.
* ``item_removed(str)``   --- ключ удалённого элемента.
* ``item_renamed(str, str)`` --- ключ + новый label.

Наследует ``section_changed(str)`` от ``BaseColumnarTab`` для backward-compat.

См. Phase 6c (plans/tab-template-extraction/plan.md).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from .base_columnar_tab import BaseColumnarTab

if TYPE_CHECKING:
    from PySide6.QtGui import QIcon

    from .tab_layout_protocol import TabLayoutProtocol

logger = logging.getLogger(__name__)


class BaseListNavTab(BaseColumnarTab):
    """Динамический CRUD-список в nav-колонке вместо tree.

    Подкласс переопределяет ``_create_item_widget(key)`` для создания
    content-виджета каждого элемента. Presenter вызывает CRUD-методы
    (``add_item``, ``remove_item``, ``rename_item``) напрямую.

    CRUD API:
        add_item(key, label, icon=None) --- добавить элемент + content widget.
        remove_item(key)               --- удалить элемент и content widget.
        rename_item(key, label)        --- изменить label элемента.
        select_item(key)               --- программно выбрать элемент.

    Hooks для подкласса:
        _create_item_widget(key) -> QWidget   --- абстрактный, content для key.
        _make_nav_item(key, label, icon)      --- default impl, кастомизация item.
    """

    # Сигналы
    item_selected = Signal(str)  # key
    item_added = Signal(str)  # key
    item_removed = Signal(str)  # key
    item_renamed = Signal(str, str)  # key, new_label

    def __init__(
        self,
        *,
        title: str,
        ctx: object,
        layout_factory: "Callable[[], TabLayoutProtocol] | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать вкладку с динамическим CRUD-списком.

        Args:
            title:          заголовок (передаётся в layout).
            ctx:            контекст приложения (generic, framework не знает тип).
            layout_factory: фабрика layout'а (TabLayoutProtocol). Обязательна.
            parent:         родительский виджет.
        """
        # Маппинг key -> QListWidgetItem (для O(1) поиска при remove/rename)
        self._key_to_item: dict[str, QListWidgetItem] = {}

        # _nav_widget будет создан через _build_nav_widget() в super().__init__
        self._nav_widget: QListWidget | None = None  # type: ignore[assignment]

        # Guard от рекурсии: _on_list_selection_changed → _on_nav_changed → ...
        self._selection_guard = False

        super().__init__(
            title=title,
            ctx=ctx,
            layout_factory=layout_factory,
            parent=parent,
        )

    # ------------------------------------------------------------------
    # Хуки BaseColumnarTab --- реализация
    # ------------------------------------------------------------------

    def _build_nav_widget(self) -> QWidget:
        """Построить QListWidget для динамической навигации."""
        nav = QListWidget()
        nav.setObjectName("ListNavWidget")
        nav.currentItemChanged.connect(self._on_list_selection_changed)
        self._nav_widget = nav
        return nav

    def _on_nav_changed(self, key: str) -> None:
        """Реагировать на смену выбора: эмитить item_selected, переключить стек.

        Вызывается из ``_on_list_selection_changed`` (user-driven) и может
        быть вызван подклассом напрямую.
        """
        if key in self._key_to_index:
            self._content_stack.setCurrentIndex(self._key_to_index[key])
        self.item_selected.emit(key)
        self.section_changed.emit(key)

    # ------------------------------------------------------------------
    # CRUD API
    # ------------------------------------------------------------------

    def add_item(
        self,
        key: str,
        label: str,
        icon: "QIcon | None" = None,
    ) -> None:
        """Добавить элемент в nav-список и зарегистрировать content widget.

        Args:
            key:   уникальный ключ элемента.
            label: отображаемый текст.
            icon:  опциональная иконка.
        """
        if key in self._key_to_item:
            logger.warning("add_item: ключ '%s' уже существует, пропускаю", key)
            return

        item = self._make_nav_item(key, label, icon)
        assert self._nav_widget is not None
        self._nav_widget.addItem(item)
        self._key_to_item[key] = item

        # Ленивая регистрация content widget
        content_widget = self._create_item_widget(key)
        self.register_content_widget(key, content_widget)

        self.item_added.emit(key)

    def remove_item(self, key: str) -> None:
        """Удалить элемент из nav-списка и content-стека.

        Args:
            key: ключ элемента для удаления.
        """
        item = self._key_to_item.pop(key, None)
        if item is None:
            logger.warning("remove_item: ключ '%s' не найден", key)
            return

        assert self._nav_widget is not None
        row = self._nav_widget.row(item)
        if row >= 0:
            self._nav_widget.takeItem(row)

        # Удалить content widget из стека
        idx = self._key_to_index.pop(key, None)
        if idx is not None:
            widget = self._content_stack.widget(idx)
            if widget is not None:
                self._content_stack.removeWidget(widget)
                widget.deleteLater()
            # Пересчитать индексы: после removeWidget все индексы > idx сдвинулись
            self._key_to_index = {k: (v - 1 if v > idx else v) for k, v in self._key_to_index.items()}

        self.item_removed.emit(key)

    def rename_item(self, key: str, label: str) -> None:
        """Изменить label элемента в nav-списке.

        Args:
            key:   ключ элемента.
            label: новый текст.
        """
        item = self._key_to_item.get(key)
        if item is None:
            logger.warning("rename_item: ключ '%s' не найден", key)
            return
        item.setText(label)
        self.item_renamed.emit(key, label)

    def select_item(self, key: str) -> None:
        """Программно выбрать элемент по ключу.

        Alias для навигации: устанавливает текущий item в QListWidget,
        что триггерит ``_on_list_selection_changed`` → ``_on_nav_changed``.
        """
        item = self._key_to_item.get(key)
        if item is None:
            logger.warning("select_item: ключ '%s' не найден", key)
            return
        assert self._nav_widget is not None
        self._nav_widget.setCurrentItem(item)

    # ------------------------------------------------------------------
    # Хуки для подкласса
    # ------------------------------------------------------------------

    def _create_item_widget(self, key: str) -> QWidget:
        """Создать content-виджет для элемента с данным ключом.

        Подкласс **обязан** переопределить этот метод.

        Note:
            Декоративно-абстрактный метод (abc.ABCMeta невозможен из-за
            metaclass conflict с QWidget/Shiboken).
        """
        raise NotImplementedError(f"{type(self).__name__} должен реализовать _create_item_widget(key)")

    def _make_nav_item(
        self,
        key: str,
        label: str,
        icon: "QIcon | None" = None,
    ) -> QListWidgetItem:
        """Создать QListWidgetItem для nav-списка.

        Default implementation. Подкласс может переопределить для
        кастомного стиля (иконки, badges, размер и т.п.).
        """
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, key)
        if icon is not None:
            item.setIcon(icon)
        return item

    # ------------------------------------------------------------------
    # Публичный API (read-only)
    # ------------------------------------------------------------------

    @property
    def nav_widget(self) -> QListWidget:
        """QListWidget навигации (для тестов и подклассов)."""
        assert self._nav_widget is not None
        return self._nav_widget

    @property
    def item_keys(self) -> list[str]:
        """Список ключей в порядке добавления (для тестов)."""
        return list(self._key_to_item.keys())

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _on_list_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        """Слот на ``currentItemChanged`` QListWidget."""
        if current is None or self._selection_guard:
            return
        key = current.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        self._on_nav_changed(key)
