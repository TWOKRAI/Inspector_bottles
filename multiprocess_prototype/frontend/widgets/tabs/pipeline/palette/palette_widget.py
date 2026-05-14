"""PluginPalette — палитра плагинов с поиском и drag-and-drop."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..graph.constants import CATEGORY_COLORS

if TYPE_CHECKING:
    pass

# MIME тип для drag-and-drop плагинов
MIME_TYPE = "application/x-inspector-plugin"

# Порядок категорий в палитре
CATEGORY_ORDER = ("source", "processing", "output", "rendering", "control", "utility", "service")

# Русские подписи категорий
CATEGORY_LABELS: dict[str, str] = {
    "source": "Source — источники",
    "processing": "Processing — обработка",
    "output": "Output — вывод",
    "rendering": "Rendering — отрисовка",
    "control": "Control — управление",
    "utility": "Utility — утилиты",
    "service": "Service — сервисы",
}

UNCATEGORIZED_LABEL = "Other — прочее"


class _PaletteTree(QTreeWidget):
    """QTreeWidget с поддержкой startDrag для операций."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QTreeWidget.DragDropMode.DragOnly)

    def startDrag(self, supportedActions):
        """Перехватить drag: только для элементов-плагинов (не категорий)."""
        item = self.currentItem()
        if item is None or item.childCount() > 0:
            return  # Не тащить категории

        plugin_name = item.data(0, Qt.ItemDataRole.UserRole)
        if not plugin_name:
            return

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_TYPE, plugin_name.encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)


class PluginPalette(QWidget):
    """Палитра плагинов с поиском и drag-and-drop.

    Принимает список плагинов [{name, category, description}],
    группирует по категории, фильтрует по поисковой строке.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._category_items: dict[str, QTreeWidgetItem] = {}
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Поиск
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск плагина...")
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        # Дерево
        self._tree = _PaletteTree()
        layout.addWidget(self._tree, stretch=1)

    @property
    def tree(self) -> _PaletteTree:
        return self._tree

    def load_plugins(self, plugins: list[dict[str, Any]]) -> None:
        """Загрузить список плагинов в палитру.

        Args:
            plugins: список dict с ключами: name, category (opt), description (opt).
        """
        self._tree.clear()
        self._category_items.clear()

        # Группировка по категории
        by_category: dict[str, list[dict]] = {}
        for p in plugins:
            cat = p.get("category", "utility")
            by_category.setdefault(cat, []).append(p)

        # Добавить в порядке CATEGORY_ORDER
        for cat in CATEGORY_ORDER:
            if cat in by_category:
                self._add_category(cat, by_category[cat])

        # Остальные категории (не в CATEGORY_ORDER)
        for cat, items in by_category.items():
            if cat not in CATEGORY_ORDER:
                self._add_category(cat, items)

        self._tree.expandAll()

    def _add_category(self, category: str, plugins: list[dict]) -> None:
        """Добавить категорию с плагинами."""
        label = CATEGORY_LABELS.get(category, f"{category.capitalize()}")
        cat_item = QTreeWidgetItem(self._tree, [label])
        cat_item.setFlags(cat_item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)

        # Цвет категории
        color = CATEGORY_COLORS.get(category, "#9e9e9e")
        cat_item.setForeground(0, QColor(color))

        self._category_items[category] = cat_item

        for p in sorted(plugins, key=lambda x: x.get("name", "")):
            name = p.get("name", "unnamed")
            desc = p.get("description", "")
            child = QTreeWidgetItem(cat_item, [name])
            child.setData(0, Qt.ItemDataRole.UserRole, name)
            if desc:
                child.setToolTip(0, desc)

    def _apply_filter(self, text: str) -> None:
        """Фильтровать плагины по name/category/description."""
        text = text.strip().lower()

        for cat_key, cat_item in self._category_items.items():
            visible_children = 0
            cat_label = CATEGORY_LABELS.get(cat_key, cat_key).lower()

            for i in range(cat_item.childCount()):
                child = cat_item.child(i)
                if not text:
                    child.setHidden(False)
                    visible_children += 1
                    continue

                name = (child.data(0, Qt.ItemDataRole.UserRole) or "").lower()
                tooltip = (child.toolTip(0) or "").lower()
                display = child.text(0).lower()

                match = text in name or text in display or text in tooltip or text in cat_label
                child.setHidden(not match)
                if match:
                    visible_children += 1

            cat_item.setHidden(visible_children == 0)

    def plugin_names_in_category(self, category: str) -> list[str]:
        """Вернуть имена плагинов в категории (для тестов)."""
        cat_item = self._category_items.get(category)
        if not cat_item:
            return []
        return [cat_item.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(cat_item.childCount())]
