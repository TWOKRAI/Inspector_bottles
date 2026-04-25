# -*- coding: utf-8 -*-
"""
TwoLevelTreeWithToolbar — дерево двух уровней + панель кнопок (как TableWithToolbar).
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from multiprocess_framework.modules.frontend_module.components.base.touch_keyboard_config import TouchKeyboardConfig
from multiprocess_framework.modules.frontend_module.core.qt_imports import QHBoxLayout, QPushButton, QVBoxLayout, QWidget, pyqtSignal
from multiprocess_framework.modules.frontend_module.widgets.tables.structured_two_level_tree import StructuredTwoLevelTreeWidget


class TwoLevelTreeWithToolbar(QWidget):
    """Тулбар + StructuredTwoLevelTreeWidget; те же сигналы, что у TableWithToolbar."""

    add_clicked = pyqtSignal()
    delete_clicked = pyqtSignal()
    move_up_clicked = pyqtSignal()
    move_down_clicked = pyqtSignal()
    copy_clicked = pyqtSignal()
    paste_clicked = pyqtSignal()

    def __init__(
        self,
        columns,
        parent=None,
        show_add_delete=True,
        show_move=True,
        show_copy_paste=True,
        touch_keyboard: TouchKeyboardConfig | dict | None = None,
        touch_keyboard_factory: Optional[Callable[[], Any]] = None,
    ):
        super().__init__(parent)
        self._columns = columns
        self._show_add_delete = show_add_delete
        self._show_move = show_move
        self._show_copy_paste = show_copy_paste
        self.tree = StructuredTwoLevelTreeWidget(
            columns=columns,
            parent=self,
            touch_keyboard=touch_keyboard,
            touch_keyboard_factory=touch_keyboard_factory,
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(30)
        if show_add_delete:
            btn_add = QPushButton("Добавить")
            btn_add.setMinimumHeight(60)
            btn_add.setMinimumWidth(200)
            btn_add.clicked.connect(self.add_clicked.emit)
            toolbar.addWidget(btn_add, 1)
            btn_del = QPushButton("Удалить")
            btn_del.setMinimumHeight(60)
            btn_del.setMinimumWidth(200)
            btn_del.clicked.connect(self.delete_clicked.emit)
            toolbar.addWidget(btn_del, 1)
        if show_move:
            btn_up = QPushButton("Вверх")
            btn_up.setMinimumHeight(60)
            btn_up.setMinimumWidth(200)
            btn_up.clicked.connect(self.move_up_clicked.emit)
            toolbar.addWidget(btn_up, 1)
            btn_down = QPushButton("Вниз")
            btn_down.setMinimumHeight(60)
            btn_down.setMinimumWidth(200)
            btn_down.clicked.connect(self.move_down_clicked.emit)
            toolbar.addWidget(btn_down, 1)
        if show_copy_paste:
            btn_copy = QPushButton("Копировать")
            btn_copy.setMinimumHeight(60)
            btn_copy.setMinimumWidth(200)
            btn_copy.clicked.connect(self.copy_clicked.emit)
            toolbar.addWidget(btn_copy, 1)
            btn_paste = QPushButton("Вставить")
            btn_paste.setMinimumHeight(60)
            btn_paste.setMinimumWidth(200)
            btn_paste.clicked.connect(self.paste_clicked.emit)
            toolbar.addWidget(btn_paste, 1)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        layout.addWidget(self.tree)

    def set_row_key(self, key):
        self.tree.set_row_key(key)

    def set_data(self, groups):
        self.tree.set_data(groups)

    def set_touch_keyboard(
        self,
        touch_keyboard: TouchKeyboardConfig | dict | None = None,
        touch_keyboard_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        self.tree.set_touch_keyboard(touch_keyboard, touch_keyboard_factory)

    def currentRow(self):
        """Совместимость с TableWithToolbar: не применимо к дереву; вернуть -1."""
        return -1

    @property
    def cell_changed(self):
        return self.tree.leaf_cell_changed
