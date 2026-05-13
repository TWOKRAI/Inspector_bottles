# -*- coding: utf-8 -*-
"""Хелперы для QTreeWidget в Settings таб.

Вспомогательные функции:
    build_nav_tree  — заполнить QTreeWidget по секциям
    find_tree_item  — рекурсивный поиск элемента по ключу
    select_tree_key — выбрать элемент дерева по ключу

Re-export CurrentPageStack из framework для удобства импорта.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

# Re-export для удобства: импортировать CurrentPageStack можно отсюда
from multiprocess_framework.modules.frontend_module.widgets.tabs import CurrentPageStack

if TYPE_CHECKING:
    pass

# Высота строки в дереве навигации (px)
_NAV_ITEM_HEIGHT = 36

__all__ = [
    "CurrentPageStack",
    "build_nav_tree",
    "find_tree_item",
    "select_tree_key",
]


def build_nav_tree(
    tree_widget: QTreeWidget,
    sections: list[tuple[str, str]],
    admin_children: list[tuple[str, str]],
) -> None:
    """Заполнить QTreeWidget секциями навигации.

    Порядок:
    1. Корневой узел «Администрация» с разворачиваемыми дочерними элементами
    2. Top-level секции из ``sections`` (список (key, title))

    Args:
        tree_widget:     QTreeWidget, который нужно заполнить
        sections:        список (key, title) для top-level секций
        admin_children:  список (key, title) для дочерних узлов «Администрация»
    """
    # --- Узел «Администрация» (разворачиваемый) ---
    admin_root = QTreeWidgetItem(tree_widget, ["Администрация"])
    admin_root.setData(0, Qt.ItemDataRole.UserRole, "admin_dashboard")
    admin_root.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))
    admin_root.setExpanded(True)

    for key, title in admin_children:
        child = QTreeWidgetItem(admin_root, [title])
        child.setData(0, Qt.ItemDataRole.UserRole, key)
        child.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))

    # --- Top-level секции ---
    for key, title in sections:
        item = QTreeWidgetItem(tree_widget, [title])
        item.setData(0, Qt.ItemDataRole.UserRole, key)
        item.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))


def find_tree_item(
    parent: QTreeWidgetItem,
    key: str,
) -> QTreeWidgetItem | None:
    """Рекурсивный поиск элемента дерева по значению UserRole.

    Args:
        parent: родительский элемент (начинать с invisibleRootItem())
        key:    искомый ключ (значение Qt.ItemDataRole.UserRole)

    Returns:
        QTreeWidgetItem если найден, иначе None
    """
    for i in range(parent.childCount()):
        child = parent.child(i)
        if child.data(0, Qt.ItemDataRole.UserRole) == key:
            return child
        found = find_tree_item(child, key)
        if found is not None:
            return found
    return None


def select_tree_key(tree_widget: QTreeWidget, key: str) -> None:
    """Выбрать элемент QTreeWidget по ключу UserRole.

    Если элемент с данным ключом не найден — ничего не делает.

    Args:
        tree_widget: целевой QTreeWidget
        key:         ключ для поиска
    """
    root = tree_widget.invisibleRootItem()
    item = find_tree_item(root, key)
    if item is not None:
        tree_widget.setCurrentItem(item)
