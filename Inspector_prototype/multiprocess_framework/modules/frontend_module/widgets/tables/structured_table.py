# -*- coding: utf-8 -*-
"""
StructuredTableWidget — универсальная таблица по конфигу колонок и данным.

Используется для: регионы, цепочки обработки, рецепты.
Колонки: текст (readonly/editable), чекбокс.
"""
from __future__ import annotations

from frontend_module.core.qt_imports import (
    QCheckBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    Qt,
    pyqtSignal,
)


class StructuredTableWidget(QTableWidget):
    """
    Таблица по конфигу колонок.
    columns: [{"key": "name", "label": "Название", "type": "text"|"checkbox", "editable": bool}, ...]
    data: list of dict (каждая строка — словарь с ключами как в columns).
    row_key: ключ в строке для идентификации (например "name" для регионов).
    """
    cell_changed = pyqtSignal(int, str, object)  # row_index, column_key, value
    row_selected = pyqtSignal(int)

    def __init__(self, columns=None, parent=None):
        super().__init__(parent)
        self._columns = columns or []
        self._data_rows = []
        self._row_key = None
        self._block_signals = False
        self.setMinimumHeight(35 * 5 + 30)
        self._setup_headers()

    def _setup_headers(self):
        self.setColumnCount(len(self._columns))
        headers = [c.get("label", c.get("key", "")) for c in self._columns]
        self.setHorizontalHeaderLabels(headers)
        self.horizontalHeader().setStretchLastSection(True)
        for i, col in enumerate(self._columns):
            if col.get("type") == "checkbox":
                self.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
            else:
                self.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)
        self.itemSelectionChanged.connect(self._on_selection_changed)

    def set_columns(self, columns):
        """Задать конфиг колонок и перестроить заголовки."""
        self._columns = list(columns)
        self.setColumnCount(len(self._columns))
        headers = [c.get("label", c.get("key", "")) for c in self._columns]
        self.setHorizontalHeaderLabels(headers)
        for i, col in enumerate(self._columns):
            if col.get("type") == "checkbox":
                self.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
            else:
                self.horizontalHeader().setSectionResizeMode(i, QHeaderView.Stretch)

    def set_row_key(self, key):
        """Ключ в данных строки для идентификации."""
        self._row_key = key

    def set_data(self, data):
        """data: list of dict или dict {row_id: row_dict}."""
        if isinstance(data, dict):
            self._data_rows = []
            for row_id, row in data.items():
                r = dict(row)
                r["_row_id"] = row_id
                self._data_rows.append(r)
        else:
            self._data_rows = list(data) if data else []

        self._block_signals = True
        self.setRowCount(len(self._data_rows))

        for row_idx, row in enumerate(self._data_rows):
            for col_idx, col in enumerate(self._columns):
                key = col.get("key")
                col_type = col.get("type", "text")
                value = row.get(key)

                if col_type == "checkbox":
                    cb = QCheckBox()
                    cb.setChecked(bool(value))
                    cb.stateChanged.connect(
                        lambda state, r=row_idx, k=key: self._on_cell_checkbox(r, k, state)
                    )
                    self.setCellWidget(row_idx, col_idx, cb)
                else:
                    item = QTableWidgetItem(str(value) if value is not None else "")
                    editable = col.get("editable", False)
                    if "_value_editable" in row:
                        editable = bool(row["_value_editable"])
                    item.setFlags(
                        item.flags() | Qt.ItemIsEnabled
                        if editable else item.flags() & ~Qt.ItemIsEditable
                    )
                    item.setData(Qt.UserRole, key)
                    self.setItem(row_idx, col_idx, item)

        self._block_signals = False
        if self.columnCount() > 0 and self.rowCount() > 0:
            self.setCurrentCell(0, 0)

    def _on_cell_checkbox(self, row_index, column_key, state):
        if self._block_signals:
            return
        value = state == Qt.Checked
        if 0 <= row_index < len(self._data_rows):
            self._data_rows[row_index][column_key] = value
        self.cell_changed.emit(row_index, column_key, value)

    def _on_selection_changed(self):
        row = self.currentRow()
        if row >= 0:
            self.row_selected.emit(row)

    def get_row_index_by_id(self, row_id):
        key = self._row_key or "_row_id"
        for i, row in enumerate(self._data_rows):
            if row.get(key) == row_id or row.get("_row_id") == row_id:
                return i
        return -1

    def get_row_data(self, row_index):
        """Вернуть словарь строки по индексу."""
        if row_index < 0 or row_index >= len(self._data_rows):
            return None
        row = dict(self._data_rows[row_index])
        for col_idx, col in enumerate(self._columns):
            if col.get("type") == "checkbox":
                w = self.cellWidget(row_index, col_idx)
                if isinstance(w, QCheckBox):
                    row[col.get("key")] = w.isChecked()
        return row

    def get_current_row_data(self):
        return self.get_row_data(self.currentRow())

    def get_all_data(self):
        return [self.get_row_data(i) for i in range(len(self._data_rows))]
