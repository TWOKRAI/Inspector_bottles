"""BaseEditorTreeView — базовое дерево редактора.

Предоставляет:
- QTreeView + QStandardItemModel с настраиваемыми колонками
- Signal suppression при программном обновлении
- Save/restore selection при refresh
- Abstract _populate() для подклассов
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from contextlib import contextmanager
from typing import Any

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QStandardItem,
    QStandardItemModel,
    QTreeView,
    QVBoxLayout,
    QWidget,
    Qt,
    Signal,
)

logger = logging.getLogger(__name__)


class BaseEditorTreeView(QWidget):
    """Базовый виджет-дерево для редакторов.

    Подклассы должны реализовать `_populate(root)` — метод заполнения
    дерева. Все остальные механизмы (signal suppression, save/restore
    selection) реализованы здесь.

    Signals:
        item_selected(str): key выбранного элемента (data Qt.UserRole).
        selection_cleared():  ничего не выбрано.
    """

    item_selected = Signal(str)
    selection_cleared = Signal()

    def __init__(
        self,
        columns: list[str],
        *,
        expand_all_on_first: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать дерево с заданными колонками.

        Args:
            columns:             Список заголовков колонок.
            expand_all_on_first: Раскрыть все узлы при первом refresh().
                                 По умолчанию True.
            parent:              Родительский виджет.
        """
        super().__init__(parent)

        # Флаг подавления сигналов при программном обновлении
        self._suppress = False

        # Раскрывать все узлы при первом вызове refresh() (когда нет сохранённого состояния)
        self._expand_all_on_first: bool = expand_all_on_first

        # Сохранённое состояние expand (None = первый вызов ещё не был)
        self._expand_state: dict | None = None

        # Модель данных
        self._model = QStandardItemModel(0, len(columns), self)
        self._model.setHorizontalHeaderLabels(columns)

        # Дерево
        self._tree = QTreeView(self)
        self._tree.setModel(self._model)
        self._tree.setRootIsDecorated(True)
        self._tree.setIndentation(20)
        self._tree.setSelectionMode(QTreeView.SelectionMode.SingleSelection)
        self._tree.header().setStretchLastSection(True)

        # Подключение сигнала смены выделения
        self._tree.selectionModel().currentChanged.connect(self._on_selection_changed)

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)

    # ------------------------------------------------------------------
    # Context manager для подавления сигналов
    # ------------------------------------------------------------------

    @contextmanager
    def _block(self):
        """Context manager: подавляет сигналы выделения на время блока."""
        self._suppress = True
        try:
            yield
        finally:
            self._suppress = False

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        """Перезаполнить дерево. Сохраняет и восстанавливает выделение и expand state."""
        selection_state = self._save_selection()
        expand_state = self._save_expand_state()

        with self._block():
            self._model.removeRows(0, self._model.rowCount())
            self._populate(self._model.invisibleRootItem())

        # При первом вызове (нет сохранённого expand state) — expandAll если флаг установлен
        if expand_state:
            self._restore_expand_state(expand_state)
        elif self._expand_all_on_first:
            self._tree.expandAll()

        self._restore_selection(selection_state)

    def select_item(self, key: str) -> None:
        """Программно выбрать элемент по ключу (data Qt.UserRole).

        Args:
            key: Ключ элемента для поиска в дереве.
        """
        with self._block():
            item = self._find_item(key)
            if item is None:
                logger.debug("select_item: элемент с key=%r не найден", key)
                return
            index = self._model.indexFromItem(item)
            self._tree.selectionModel().setCurrentIndex(
                index,
                self._tree.selectionModel().SelectionFlag.ClearAndSelect,
            )
            self._tree.scrollTo(index)

    # ------------------------------------------------------------------
    # Save / restore selection
    # ------------------------------------------------------------------

    def _save_selection(self) -> Any:
        """Сохранить текущий выбор.

        Возвращает data(Qt.UserRole) текущего item или None.
        Подклассы могут переопределить для более сложной логики.
        """
        index = self._tree.selectionModel().currentIndex()
        if not index.isValid():
            return None
        # Берём данные из первой колонки строки
        first_col = self._model.index(index.row(), 0, index.parent())
        item = self._model.itemFromIndex(first_col)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _restore_selection(self, state: Any) -> None:
        """Восстановить выбор по сохранённому состоянию.

        Ищет item с data(Qt.UserRole) == state и выбирает его.
        Подклассы могут переопределить.

        Args:
            state: Значение, сохранённое в _save_selection().
        """
        if state is None:
            return
        item = self._find_item(str(state))
        if item is None:
            return
        with self._block():
            index = self._model.indexFromItem(item)
            self._tree.selectionModel().setCurrentIndex(
                index,
                self._tree.selectionModel().SelectionFlag.ClearAndSelect,
            )
            self._tree.scrollTo(index)

    # ------------------------------------------------------------------
    # Save / restore expand state
    # ------------------------------------------------------------------

    def _save_expand_state(self) -> dict:
        """Сохранить состояние раскрытия узлов дерева.

        Обходит дочерние элементы корня рекурсивно и сохраняет
        {data(Qt.UserRole): is_expanded} для каждого узла.

        Returns:
            Словарь {ключ_узла: bool} или пустой dict если дерево пустое.
        """
        result: dict = {}
        root = self._model.invisibleRootItem()
        self._collect_expand_state(root, result)
        return result

    def _collect_expand_state(self, parent: QStandardItem, result: dict) -> None:
        """Рекурсивно собрать expand state дочерних узлов.

        Args:
            parent: Родительский item для обхода.
            result: Словарь для накопления результатов.
        """
        for row in range(parent.rowCount()):
            item = parent.child(row, 0)
            if item is None:
                continue
            key = item.data(Qt.ItemDataRole.UserRole)
            if key is not None:
                index = self._model.indexFromItem(item)
                result[key] = self._tree.isExpanded(index)
            # Рекурсивно обходим дочерние узлы
            if item.hasChildren():
                self._collect_expand_state(item, result)

    def _restore_expand_state(self, state: dict) -> None:
        """Восстановить состояние раскрытия узлов из сохранённого словаря.

        Args:
            state: Словарь {ключ_узла: bool}, сохранённый в _save_expand_state().
        """
        if not state:
            return
        root = self._model.invisibleRootItem()
        self._apply_expand_state(root, state)

    def _apply_expand_state(self, parent: QStandardItem, state: dict) -> None:
        """Рекурсивно применить expand state к дочерним узлам.

        Args:
            parent: Родительский item для обхода.
            state:  Словарь {ключ_узла: bool}.
        """
        for row in range(parent.rowCount()):
            item = parent.child(row, 0)
            if item is None:
                continue
            key = item.data(Qt.ItemDataRole.UserRole)
            if key is not None and key in state:
                index = self._model.indexFromItem(item)
                if state[key]:
                    self._tree.expand(index)
                else:
                    self._tree.collapse(index)
            # Рекурсивно применяем к дочерним узлам
            if item.hasChildren():
                self._apply_expand_state(item, state)

    # ------------------------------------------------------------------
    # Абстрактный метод заполнения
    # ------------------------------------------------------------------

    @abstractmethod
    def _populate(self, root: QStandardItem) -> None:
        """Заполнить дерево.

        Подкласс добавляет дочерние элементы к root
        (invisibleRootItem модели).

        Args:
            root: Корневой элемент модели (invisibleRootItem).
        """

    # ------------------------------------------------------------------
    # Обработчик сигнала выделения
    # ------------------------------------------------------------------

    def _on_selection_changed(self, current, previous) -> None:
        """Обработать смену выделения в дереве.

        Пропускает события при _suppress == True.
        """
        if self._suppress:
            return

        if not current.isValid():
            self.selection_cleared.emit()
            return

        # Ключ хранится в первой колонке строки через Qt.UserRole
        first_col = self._model.index(current.row(), 0, current.parent())
        item = self._model.itemFromIndex(first_col)
        if item is None:
            self.selection_cleared.emit()
            return

        key = item.data(Qt.ItemDataRole.UserRole)
        if key is not None:
            self.item_selected.emit(str(key))
        else:
            self.selection_cleared.emit()

    # ------------------------------------------------------------------
    # Вспомогательный рекурсивный поиск
    # ------------------------------------------------------------------

    def _find_item(
        self,
        key: str,
        parent: QStandardItem | None = None,
    ) -> QStandardItem | None:
        """Рекурсивно найти item по data(Qt.UserRole) == key.

        Args:
            key:    Искомый ключ.
            parent: Узел, с которого начинать поиск. По умолчанию —
                    invisibleRootItem модели.

        Returns:
            Найденный QStandardItem или None.
        """
        if parent is None:
            parent = self._model.invisibleRootItem()

        for row in range(parent.rowCount()):
            item = parent.child(row, 0)
            if item is None:
                continue
            if item.data(Qt.ItemDataRole.UserRole) == key:
                return item
            # Рекурсивный поиск по дочерним элементам
            found = self._find_item(key, item)
            if found is not None:
                return found

        return None


__all__ = ["BaseEditorTreeView"]
