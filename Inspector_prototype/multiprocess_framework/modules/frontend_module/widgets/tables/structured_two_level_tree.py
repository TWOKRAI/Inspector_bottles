# -*- coding: utf-8 -*-
"""
StructuredTwoLevelTreeWidget — дерево из двух уровней: группа → строки данных.

Верхний уровень (группа): только подпись в первой колонке, без редактирования.
Листья: те же колонки, что у StructuredTableWidget (text / checkbox).

groups: list of (group_id: str, rows: list[dict]) — строки с ключами из columns и
идентификатором листа в row_key (например region_id).
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from frontend_module.components.base.touch_keyboard_config import (
    TouchKeyboardConfig,
    coerce_touch_keyboard,
)
from frontend_module.core.qt_imports import (
    QAbstractItemView,
    QCheckBox,
    QHeaderView,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    Qt,
    pyqtSignal,
)

from frontend_module.widgets.tables.touch_line_edit_delegate import TouchLineEditItemDelegate


ROLE_KIND = Qt.UserRole
ROLE_GROUP = Qt.UserRole + 1
ROLE_LEAF = Qt.UserRole + 2


class StructuredTwoLevelTreeWidget(QTreeWidget):
    """
    Двухуровневое дерево: группа → строки с колонками как у StructuredTableWidget.

    Выбор: подключайте currentItemChanged к слоту и вызывайте get_selection().

    leaf_cell_changed(str group_id, str row_id, str column_key, object value)
    """

    leaf_cell_changed = pyqtSignal(str, str, str, object)

    def __init__(
        self,
        columns: Optional[List[Dict[str, Any]]] = None,
        parent=None,
        touch_keyboard: TouchKeyboardConfig | dict | None = None,
        touch_keyboard_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(parent)
        self._columns = columns or []
        self._row_key = "region_id"
        self._block_signals = False
        self._touch_keyboard = coerce_touch_keyboard(touch_keyboard)
        self._touch_keyboard_factory = touch_keyboard_factory
        self._touch_line_edit_delegate_installed = False
        self.setMinimumHeight(35 * 5 + 30)
        self.setAnimated(True)
        self.setIndentation(20)
        self.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.SelectedClicked
        )
        self.setAlternatingRowColors(True)
        self.setColumnCount(len(self._columns))
        headers = [c.get("label", c.get("key", "")) for c in self._columns]
        self.setHeaderLabels(headers)
        self.header().setStretchLastSection(True)
        for i, col in enumerate(self._columns):
            if col.get("type") == "checkbox":
                self.header().setSectionResizeMode(i, QHeaderView.ResizeToContents)
            else:
                self.header().setSectionResizeMode(i, QHeaderView.Stretch)
        self.itemChanged.connect(self._on_item_changed)
        self._refresh_touch_delegate()

    def _keyboard_config_for_column(self, col_idx: int) -> Optional[TouchKeyboardConfig]:
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
        self._touch_keyboard = coerce_touch_keyboard(touch_keyboard)
        self._touch_keyboard_factory = touch_keyboard_factory
        self._refresh_touch_delegate()

    def _touch_keyboard_effective(self) -> bool:
        if self._touch_keyboard is not None or self._touch_keyboard_factory is not None:
            return True
        return any(c.get("touch_keyboard") is not None for c in self._columns)

    def _line_edit_column_indices(self) -> List[int]:
        """Колонки не-checkbox: для них ставим touch-делегат отдельно от чекбоксов."""
        return [i for i, c in enumerate(self._columns) if c.get("type", "text") != "checkbox"]

    def _refresh_touch_delegate(self) -> None:
        """
        Touch-делегат только на текстовых колонках (``setItemDelegateForColumn``), не на весь вид.

        Не вызывать ``setItemDelegate(None)`` / ``setItemDelegateForColumn(..., None)``: на Windows
        (PyQt5) это портит внутренности ``QTreeWidget``; сброс — через ``QStyledItemDelegate(self)``.
        """
        line_cols = self._line_edit_column_indices()
        if self._touch_line_edit_delegate_installed:
            for i in line_cols:
                self.setItemDelegateForColumn(i, QStyledItemDelegate(self))
            self._touch_line_edit_delegate_installed = False
        if not self._touch_keyboard_effective():
            return
        if not line_cols:
            return
        delegate = TouchLineEditItemDelegate(self, self._touch_keyboard_factory)
        for i in line_cols:
            self.setItemDelegateForColumn(i, delegate)
        self._touch_line_edit_delegate_installed = True

    def set_row_key(self, key: str) -> None:
        self._row_key = key

    def set_columns(self, columns: List[Dict[str, Any]]) -> None:
        self._columns = list(columns)
        self.setColumnCount(len(self._columns))
        headers = [c.get("label", c.get("key", "")) for c in self._columns]
        self.setHeaderLabels(headers)
        for i, col in enumerate(self._columns):
            if col.get("type") == "checkbox":
                self.header().setSectionResizeMode(i, QHeaderView.ResizeToContents)
            else:
                self.header().setSectionResizeMode(i, QHeaderView.Stretch)
        self._refresh_touch_delegate()

    def set_data(self, groups: List[Tuple[str, List[Dict[str, Any]]]]) -> None:
        """groups: [(group_id, [row_dict, ...]), ...]. row_dict — ключи как в columns + row_key."""
        self._block_signals = True
        self.clear()

        for group_id, rows in groups:
            g_item = QTreeWidgetItem()
            g_item.setData(0, ROLE_KIND, "group")
            g_item.setData(0, ROLE_GROUP, group_id)
            g_item.setText(0, str(group_id))
            for c in range(1, len(self._columns)):
                g_item.setText(c, "")
            g_item.setFlags(g_item.flags() & ~Qt.ItemIsEditable)

            for row in rows:
                leaf = QTreeWidgetItem(g_item)
                leaf.setData(0, ROLE_KIND, "leaf")
                leaf.setData(0, ROLE_GROUP, group_id)
                rid = row.get(self._row_key) or row.get("name") or ""
                leaf.setData(0, ROLE_LEAF, str(rid))

                for col_idx, col in enumerate(self._columns):
                    key = col.get("key")
                    col_type = col.get("type", "text")
                    value = row.get(key)
                    if col_type == "checkbox":
                        leaf.setText(col_idx, "")
                        cb = QCheckBox()
                        cb.setChecked(bool(value))
                        cb.stateChanged.connect(
                            lambda state, g=group_id, r=str(rid), k=key: self._on_leaf_checkbox(
                                g, r, k, state == Qt.Checked
                            )
                        )
                        self.setItemWidget(leaf, col_idx, cb)
                    else:
                        leaf.setText(col_idx, str(value) if value is not None else "")
                        editable = col.get("editable", False)
                        if "_value_editable" in row:
                            editable = bool(row["_value_editable"])
                        base = leaf.flags()
                        if editable:
                            leaf.setFlags(base | Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                        else:
                            leaf.setFlags((base | Qt.ItemIsEnabled | Qt.ItemIsSelectable) & ~Qt.ItemIsEditable)

            self.addTopLevelItem(g_item)
            g_item.setExpanded(True)

        self._block_signals = False

    def _on_leaf_checkbox(self, group_id: str, row_id: str, column_key: str, value: bool) -> None:
        if self._block_signals:
            return
        self.leaf_cell_changed.emit(group_id, row_id, column_key, value)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._block_signals:
            return
        if item.data(0, ROLE_KIND) != "leaf":
            return
        if column < 0 or column >= len(self._columns):
            return
        col = self._columns[column]
        if col.get("type") == "checkbox":
            return
        gid = item.data(0, ROLE_GROUP)
        lid = item.data(0, ROLE_LEAF)
        if gid is None or lid is None:
            return
        key = col.get("key", "")
        text = item.text(column)
        self.leaf_cell_changed.emit(str(gid), str(lid), key, text)

    def get_selection(self) -> Tuple[Optional[str], Optional[str]]:
        """(group_id, leaf_id) — leaf_id None если выбрана только группа."""
        cur = self.currentItem()
        if cur is None:
            return (None, None)
        kind = cur.data(0, ROLE_KIND)
        gid = cur.data(0, ROLE_GROUP)
        if not gid:
            return (None, None)
        if kind == "group":
            return (str(gid), None)
        lid = cur.data(0, ROLE_LEAF)
        return (str(gid), str(lid) if lid is not None else None)

    def select_leaf(self, group_id: str, row_id: str) -> bool:
        """Выделить лист с row_key == row_id под указанной группой."""
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if top.data(0, ROLE_KIND) != "group":
                continue
            if str(top.data(0, ROLE_GROUP)) != group_id:
                continue
            top.setExpanded(True)
            for j in range(top.childCount()):
                ch = top.child(j)
                if ch.data(0, ROLE_KIND) != "leaf":
                    continue
                if str(ch.data(0, ROLE_LEAF)) == row_id:
                    self._block_signals = True
                    self.setCurrentItem(ch)
                    self.scrollToItem(ch)
                    self._block_signals = False
                    return True
        return False

    def select_group(self, group_id: str) -> bool:
        """Выделить узел группы (камера без выбранного региона)."""
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if top.data(0, ROLE_KIND) != "group":
                continue
            if str(top.data(0, ROLE_GROUP)) == group_id:
                self._block_signals = True
                top.setExpanded(True)
                self.setCurrentItem(top)
                self.scrollToItem(top)
                self._block_signals = False
                return True
        return False

    def clear_selection_only(self) -> None:
        """Снять выделение (без очистки дерева)."""
        self._block_signals = True
        self.clearSelection()
        self._block_signals = False

    def set_leaf_cell_text(self, group_id: str, row_id: str, column_key: str, text: str) -> bool:
        """Программно выставить текст ячейки листа (откат после ошибки валидации)."""
        col_idx = next(
            (i for i, c in enumerate(self._columns) if c.get("key") == column_key),
            -1,
        )
        if col_idx < 0:
            return False
        col = self._columns[col_idx]
        if col.get("type") == "checkbox":
            return False
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if str(top.data(0, ROLE_GROUP)) != group_id:
                continue
            for j in range(top.childCount()):
                ch = top.child(j)
                if ch.data(0, ROLE_KIND) != "leaf" or str(ch.data(0, ROLE_LEAF)) != row_id:
                    continue
                self._block_signals = True
                ch.setText(col_idx, text)
                self._block_signals = False
                return True
        return False

    def leaf_row_values(self, group_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        """Собрать значения строки листа (чекбоксы с виджетов, текст с item)."""
        for i in range(self.topLevelItemCount()):
            top = self.topLevelItem(i)
            if str(top.data(0, ROLE_GROUP)) != group_id:
                continue
            for j in range(top.childCount()):
                ch = top.child(j)
                if ch.data(0, ROLE_KIND) != "leaf" or str(ch.data(0, ROLE_LEAF)) != row_id:
                    continue
                out: Dict[str, Any] = {self._row_key: row_id}
                for col_idx, col in enumerate(self._columns):
                    key = col.get("key")
                    if col.get("type") == "checkbox":
                        w = self.itemWidget(ch, col_idx)
                        if isinstance(w, QCheckBox):
                            out[key] = w.isChecked()
                    else:
                        out[key] = ch.text(col_idx).strip()
                return out
        return None
