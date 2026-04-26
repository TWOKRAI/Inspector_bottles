"""Контекстные меню графового редактора."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu


def show_node_context_menu(
    scene: Any,
    node_item: Any,
    screen_pos: QPoint,
) -> None:
    """Контекстное меню для узла: включить/отключить, дублировать, удалить."""
    menu = QMenu()

    # Включить / Отключить
    is_enabled = node_item.opacity() > 0.5
    toggle_text = "Отключить" if is_enabled else "Включить"
    toggle_action = menu.addAction(toggle_text)

    # Дублировать
    duplicate_action = menu.addAction("Дублировать")

    menu.addSeparator()

    # Удалить
    delete_action = menu.addAction("Удалить")

    chosen = menu.exec(screen_pos)

    if chosen == toggle_action:
        new_enabled = not is_enabled
        node_item.set_enabled(new_enabled)
        scene.node_toggled.emit(node_item.node_id, new_enabled)

    elif chosen == duplicate_action:
        scene.duplicate_node(node_item)

    elif chosen == delete_action:
        scene.delete_node_with_signal(node_item.node_id)


def show_edge_context_menu(
    scene: Any,
    edge_item: Any,
    screen_pos: QPoint,
) -> None:
    """Контекстное меню для ребра: удалить соединение."""
    menu = QMenu()
    delete_action = menu.addAction("Удалить соединение")

    chosen = menu.exec(screen_pos)

    if chosen == delete_action:
        scene.remove_edge_with_signal(edge_item)


def show_scene_context_menu(
    view: Any,
    screen_pos: QPoint,
) -> None:
    """Контекстное меню для пустого места: подогнать масштаб, выделить всё."""
    menu = QMenu()
    fit_action = menu.addAction("Подогнать масштаб")
    select_all_action = menu.addAction("Выделить всё")

    chosen = menu.exec(screen_pos)

    if chosen == fit_action:
        view.fit_all()

    elif chosen == select_all_action:
        scene = view.scene()
        if scene is not None:
            for item in scene.items():
                item.setSelected(True)
