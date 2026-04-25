# -*- coding: utf-8 -*-
"""
StructuredTableWidget — универсальная таблица по конфигу колонок и данным.

Используется для: регионы, цепочки обработки, рецепты.
Колонки: текст (readonly/editable), чекбокс.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from multiprocess_framework.modules.frontend_module.components.base.touch_keyboard_config import (
    TouchKeyboardConfig,
    coerce_touch_keyboard,
)
from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QAbstractItemView,
    QCheckBox,
    QHeaderView,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    Qt,
    Signal,
)
from multiprocess_framework.modules.frontend_module.widgets.tables.touch_line_edit_delegate import TouchLineEditItemDelegate


class StructuredTableWidget(QTableWidget):
    """
    Таблица по конфигу колонок.
    columns: [{"key": "name", "label": "Название", "type": "text"|"checkbox", "editable": bool}, ...]
    data: list of dict (каждая строка — словарь с ключами как в columns).
    row_key: ключ в строке для идентификации (например "name" для регионов).
    """
    cell_changed = Signal(int, str, object)  # row_index, column_key, value
    row_selected = Signal(int)

    def __init__(
        self,
        columns=None,
        parent=None,
        touch_keyboard: TouchKeyboardConfig | dict | None = None,
        touch_keyboard_factory: Optional[Callable[[], Any]] = None,
    ):
        super().__init__(parent)
        self._columns = columns or []
        self._data_rows = []
        self._row_key = None
        self._block_signals = False
        self._touch_keyboard = coerce_touch_keyboard(touch_keyboard)
        self._touch_keyboard_factory = touch_keyboard_factory
        self._touch_line_edit_delegate_installed = False
        self.setMinimumHeight(35 * 5 + 30)
        self._setup_headers()
        self._refresh_touch_delegate()
        self.itemChanged.connect(self._on_item_changed)

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

    def _keyboard_config_for_column(self, col_idx: int) -> Optional[TouchKeyboardConfig]:
        """Переопределение touch-клавиатуры: ключ колонки ``touch_keyboard`` (dict или dataclass)."""
        if col_idx < 0 or col_idx >= len(self._columns):
            return self._touch_keyboard
        col = self._columns[col_idx]
        raw = col.get("touch_keyboard")
        if raw is not None:
            return coerce_touch_keyboard(raw)
        if self._touch_keyboard is None and self._touch_keyboard_factory is None:
            return None
        return self._touch_keyboard

    def set_touch_keyboard(
        self,
        touch_keyboard: TouchKeyboardConfig | dict | None = None,
        touch_keyboard_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Включить/выключить touch-клавиатуру после создания виджета."""
        self._touch_keyboard = coerce_touch_keyboard(touch_keyboard)
        self._touch_keyboard_factory = touch_keyboard_factory
        self._refresh_touch_delegate()

    def _touch_keyboard_effective(self) -> bool:
        if self._touch_keyboard is not None or self._touch_keyboard_factory is not None:
            return True
        return any(c.get("touch_keyboard") is not None for c in self._columns)

    def _line_edit_column_indices(self) -> List[int]:
        return [i for i, c in enumerate(self._columns) if c.get("type", "text") != "checkbox"]

    def _refresh_touch_delegate(self) -> None:
        """
        Touch-делегат только на текстовых колонках; сброс через ``QStyledItemDelegate``, не ``None``.

        См. ``StructuredTwoLevelTreeWidget._refresh_touch_delegate``.
        """
        line_cols = self._line_edit_column_indices()
        if self._touch_line_edit_delegate_installed:
            for i in line_cols:
                self.setItemDelegateForColumn(i, QStyledItemDelegate(self))
            self._touch_line_edit_delegate_installed = False
            self.setEditTriggers(
                QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            )
        if not self._touch_keyboard_effective():
            return
        if not line_cols:
            return
        delegate = TouchLineEditItemDelegate(self, self._touch_keyboard_factory)
        for i in line_cols:
            self.setItemDelegateForColumn(i, delegate)
        self._touch_line_edit_delegate_installed = True
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
        )

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
        self._refresh_touch_delegate()

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
                        item.flags() | Qt.ItemFlag.ItemIsEnabled
                        if editable else item.flags() & ~Qt.ItemFlag.ItemIsEditable
                    )
                    item.setData(Qt.ItemDataRole.UserRole, key)
                    self.setItem(row_idx, col_idx, item)

        self._block_signals = False
        if self.columnCount() > 0 and self.rowCount() > 0:
            self.setCurrentCell(0, 0)

    def _on_cell_checkbox(self, row_index, column_key, state):
        if self._block_signals:
            return
        # PySide6: stateChanged(int), Qt.Checked = enum — сравниваем через .value
        value = state == Qt.Checked.value
        if 0 <= row_index < len(self._data_rows):
            self._data_rows[row_index][column_key] = value
        self.cell_changed.emit(row_index, column_key, value)

    def _on_selection_changed(self):
        row = self.currentRow()
        if row >= 0:
            self.row_selected.emit(row)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._block_signals:
            return
        col = item.column()
        row = item.row()
        if col < 0 or row < 0 or row >= len(self._data_rows):
            return
        col_spec = self._columns[col]
        if col_spec.get("type") == "checkbox":
            return
        key = col_spec.get("key")
        if not key:
            return
        text = item.text()
        self._data_rows[row][key] = text
        self.cell_changed.emit(row, key, text)

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
