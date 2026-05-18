# -*- coding: utf-8 -*-
"""Утилиты для QTreeWidget в вкладках с tree-навигацией.

Извлечены из ``multiprocess_prototype/frontend/widgets/tabs/settings/_nav_tree.py``
в framework для переиспользования в ``BaseTreeNavTab`` и будущих табах.

Функции:
    build_nav_tree        --- заполнить QTreeWidget по спискам секций
    build_nav_tree_from_specs --- заполнить QTreeWidget по ``list[SectionSpec]``
    collapse_other_branches --- свернуть все ветки кроме активной
    find_tree_item        --- рекурсивный поиск элемента по ключу
    select_tree_key       --- выбрать элемент дерева по ключу

См. ADR-126.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

if TYPE_CHECKING:
    from .section_spec import SectionSpec

# Высота строки в дереве навигации (px)
_NAV_ITEM_HEIGHT = 36

__all__ = [
    "build_nav_tree",
    "build_nav_tree_from_specs",
    "collapse_other_branches",
    "find_tree_item",
    "select_tree_key",
]


def build_nav_tree(
    tree_widget: QTreeWidget,
    sections: list[tuple[str, str]],
    admin_children: list[tuple[str, str]],
) -> None:
    """Заполнить QTreeWidget секциями навигации (legacy API для Settings).

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
    admin_root.setExpanded(False)

    for key, title in admin_children:
        child = QTreeWidgetItem(admin_root, [title])
        child.setData(0, Qt.ItemDataRole.UserRole, key)
        child.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))

    # --- Top-level секции ---
    for key, title in sections:
        item = QTreeWidgetItem(tree_widget, [title])
        item.setData(0, Qt.ItemDataRole.UserRole, key)
        item.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))


def build_nav_tree_from_specs(
    tree_widget: QTreeWidget,
    specs: "list[SectionSpec]",
) -> None:
    """Заполнить QTreeWidget по ``list[SectionSpec]`` (новый API).

    Строит иерархию: top-level узлы (``parent_key=None``) и дочерние
    (``parent_key=<key>``). Поддерживает произвольную глубину вложенности.

    Args:
        tree_widget: QTreeWidget для заполнения.
        specs:       список SectionSpec (порядок определяет порядок в дереве).
    """
    # Маппинг key → QTreeWidgetItem для вложенности
    items: dict[str, QTreeWidgetItem] = {}

    # Сначала top-level, потом дочерние (два прохода для стабильности)
    for spec in specs:
        if spec.parent_key is not None:
            continue
        item = QTreeWidgetItem(tree_widget, [spec.title])
        item.setData(0, Qt.ItemDataRole.UserRole, spec.key)
        item.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))
        items[spec.key] = item

    for spec in specs:
        if spec.parent_key is None:
            continue
        parent_item = items.get(spec.parent_key)
        if parent_item is None:
            # Родитель не найден — добавить как top-level (robustness)
            parent_item = tree_widget.invisibleRootItem()
        child = QTreeWidgetItem(parent_item, [spec.title])
        child.setData(0, Qt.ItemDataRole.UserRole, spec.key)
        child.setSizeHint(0, QSize(0, _NAV_ITEM_HEIGHT))
        items[spec.key] = child


def collapse_other_branches(
    tree_widget: QTreeWidget,
    current_item: QTreeWidgetItem,
) -> None:
    """Свернуть все ветки кроме той, к которой принадлежит текущий элемент.

    Если выбран top-level узел с детьми --- раскрыть его.
    Если выбран дочерний узел --- раскрыть его родителя.
    Все остальные top-level узлы с детьми --- свернуть.

    Args:
        tree_widget:   QTreeWidget
        current_item:  текущий выбранный элемент
    """
    root = tree_widget.invisibleRootItem()

    # Определить «активный» top-level узел
    active_top = current_item
    while active_top.parent() is not None:
        active_top = active_top.parent()

    for i in range(root.childCount()):
        top_item = root.child(i)
        if top_item.childCount() == 0:
            continue
        # Раскрыть ветку активного элемента, свернуть остальные
        top_item.setExpanded(top_item is active_top)


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

    Если элемент с данным ключом не найден --- ничего не делает.

    Args:
        tree_widget: целевой QTreeWidget
        key:         ключ для поиска
    """
    root = tree_widget.invisibleRootItem()
    item = find_tree_item(root, key)
    if item is not None:
        tree_widget.setCurrentItem(item)
