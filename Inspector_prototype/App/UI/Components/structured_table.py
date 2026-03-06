# -*- coding: utf-8 -*-
"""
Универсальный виджет таблицы по конфигу колонок и данным (список/словарь).
Используется для: Регионы/Изображения, Цепочки обработки, рецепты.
Колонки: текст (readonly/editable), чекбокс.
"""
from PyQt5.QtWidgets import (
    QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView, QWidget, QHBoxLayout
)
from PyQt5.QtCore import Qt, pyqtSignal


class StructuredTableWidget(QTableWidget):
    """
    Таблица по конфигу колонок.
    columns: [{"key": "name", "label": "Название", "type": "text"|"checkbox", "editable": bool}, ...]
    data: list of dict (каждая строка — словарь с ключами как в columns).
    row_key: ключ в строке, по которому однозначно идентифицировать строку (например "name" для регионов).
    """
    cell_changed = pyqtSignal(int, str, object)  # row_index, column_key, value
    row_selected = pyqtSignal(int)

    def __init__(self, columns=None, parent=None):
        super().__init__(parent)
        self._columns = columns or []
        self._data_rows = []  # list of dict
        self._row_key = None  # optional key for row id
        self._block_signals = False
        # Устанавливаем минимальную высоту на 5 строк (примерно 35px на строку + заголовок)
        self.setMinimumHeight(35 * 5 + 30)  # 5 строк + заголовок
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
        """Ключ в данных строки для идентификации (например 'name')."""
        self._row_key = key

    def set_data(self, data):
        """
        data: list of dict (каждая строка — словарь по колонкам),
        либо dict (ключ — id строки, значение — словарь) — преобразуем в list, сохраняя _id в каждой строке.
        """
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
        """Найти индекс строки по _row_id или по полю row_key."""
        key = self._row_key or "_row_id"
        for i, row in enumerate(self._data_rows):
            if row.get(key) == row_id or row.get("_row_id") == row_id:
                return i
        return -1

    def get_row_data(self, row_index):
        """Вернуть словарь строки по индексу (включая обновления из чекбоксов)."""
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
        """Данные выбранной строки."""
        return self.get_row_data(self.currentRow())

    def get_all_data(self):
        """Актуальные данные таблицы (с учётом чекбоксов)."""
        out = []
        for i in range(len(self._data_rows)):
            out.append(self.get_row_data(i))
        return out
