# -*- coding: utf-8 -*-
"""
TableWithToolbar — таблица + панель кнопок (Добавить, Удалить, Вверх, Вниз, Копировать, Вставить).
"""
from __future__ import annotations

from frontend_module.components.structured_table import StructuredTableWidget
from frontend_module.core.qt_imports import QHBoxLayout, QPushButton, QVBoxLayout, QWidget, pyqtSignal


class TableWithToolbar(QWidget):
    """Таблица с панелью: Добавить, Удалить, Вверх, Вниз, Копировать, Вставить."""
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
    ):
        super().__init__(parent)
        self._columns = columns
        self._show_add_delete = show_add_delete
        self._show_move = show_move
        self._show_copy_paste = show_copy_paste
        self.table = StructuredTableWidget(columns=columns, parent=self)
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
        layout.addWidget(self.table)

    def set_row_key(self, key):
        self.table.set_row_key(key)

    def set_data(self, data):
        self.table.set_data(data)

    def set_columns(self, columns):
        self.table.set_columns(columns)

    def currentRow(self):
        return self.table.currentRow()

    def get_row_data(self, row_index):
        return self.table.get_row_data(row_index)

    def get_current_row_data(self):
        return self.table.get_current_row_data()

    def get_all_data(self):
        return self.table.get_all_data()

    @property
    def cell_changed(self):
        return self.table.cell_changed

    @property
    def row_selected(self):
        return self.table.row_selected
