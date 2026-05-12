"""TreeNavWidget — 2-уровневое дерево навигации (категория -> подкатегория).

Переиспользуемый примитив для 2-уровневой навигации.
Категории — нередактируемые/неселектабельные заголовки,
подкатегории — кликабельные листья.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget


class TreeNavWidget(QWidget):
    """2-уровневое дерево навигации (категория -> подкатегория).

    Сигналы:
        leaf_selected(category_key, subcategory_key) — выбран лист.
        category_selected(category_key) — клик по категории.
    """

    leaf_selected = Signal(str, str)
    category_selected = Signal(str)

    # Роль для хранения ключа элемента
    _KEY_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, nav_width: int = 200, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TreeNavWidget")

        self._tree = QTreeWidget()
        self._tree.setObjectName("TreeNavWidget_tree")
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(True)
        self.setFixedWidth(nav_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)

        # Сигналы
        self._tree.currentItemChanged.connect(self._on_current_changed)
        self._tree.itemClicked.connect(self._on_item_clicked)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_tree(self, tree: dict[str, list[str]]) -> None:
        """Загрузить дерево: {категория: [подкатегория, ...]}.

        Категории с пустым списком подкатегорий не отображаются.
        """
        self._tree.clear()
        for category, subcategories in tree.items():
            if not subcategories:
                # Пустая категория — не отображать
                continue
            cat_item = QTreeWidgetItem(self._tree, [category])
            cat_item.setData(0, self._KEY_ROLE, category)
            # Категория: доступна, но не селектабельна
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled)

            for sub in subcategories:
                sub_item = QTreeWidgetItem(cat_item, [sub])
                sub_item.setData(0, self._KEY_ROLE, sub)
                sub_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                )

    def filter(self, text: str) -> None:
        """Скрыть несовпадающие листы. Пустые категории — скрывать."""
        needle = text.lower()
        root = self._tree.invisibleRootItem()
        for cat_idx in range(root.childCount()):
            cat_item = root.child(cat_idx)
            visible_children = 0
            for sub_idx in range(cat_item.childCount()):
                sub_item = cat_item.child(sub_idx)
                matches = needle in sub_item.text(0).lower()
                sub_item.setHidden(not matches)
                if matches:
                    visible_children += 1
            # Категория с 0 видимых детей — скрыть
            cat_item.setHidden(visible_children == 0)
            # Категория с видимыми детьми — развернуть
            if visible_children > 0:
                cat_item.setExpanded(True)

    def clear_filter(self) -> None:
        """Показать все items, свернуть обратно."""
        root = self._tree.invisibleRootItem()
        for cat_idx in range(root.childCount()):
            cat_item = root.child(cat_idx)
            cat_item.setHidden(False)
            cat_item.setExpanded(False)
            for sub_idx in range(cat_item.childCount()):
                cat_item.child(sub_idx).setHidden(False)

    def select(self, category: str, subcategory: str) -> None:
        """Программно выделить подкатегорию."""
        root = self._tree.invisibleRootItem()
        for cat_idx in range(root.childCount()):
            cat_item = root.child(cat_idx)
            if cat_item.data(0, self._KEY_ROLE) != category:
                continue
            for sub_idx in range(cat_item.childCount()):
                sub_item = cat_item.child(sub_idx)
                if sub_item.data(0, self._KEY_ROLE) == subcategory:
                    cat_item.setExpanded(True)
                    self._tree.setCurrentItem(sub_item)
                    return

    def current_selection(self) -> tuple[str, str] | None:
        """Текущий выделенный лист: (category, subcategory) или None."""
        item = self._tree.currentItem()
        if item is None or item.parent() is None:
            # Нет выделения или выделена категория
            return None
        category = item.parent().data(0, self._KEY_ROLE)
        subcategory = item.data(0, self._KEY_ROLE)
        return (category, subcategory)

    # ------------------------------------------------------------------
    # Внутренние обработчики
    # ------------------------------------------------------------------

    def _on_current_changed(
        self, current: QTreeWidgetItem | None, _previous: QTreeWidgetItem | None
    ) -> None:
        """Обработка смены текущего элемента — эмит leaf_selected для листьев."""
        if current is None:
            return
        if current.parent() is not None:
            # Это лист (подкатегория)
            category = current.parent().data(0, self._KEY_ROLE)
            subcategory = current.data(0, self._KEY_ROLE)
            self.leaf_selected.emit(category, subcategory)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Обработка клика — эмит category_selected для категорий."""
        if item.parent() is None:
            # Это категория (top-level)
            category = item.data(0, self._KEY_ROLE)
            self.category_selected.emit(category)
