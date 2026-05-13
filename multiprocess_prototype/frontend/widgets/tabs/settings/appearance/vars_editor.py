# -*- coding: utf-8 -*-
"""VarsEditor -- виджет редактирования переменных темы.

Содержит TreeNavWidget (навигация по категориям) + QTableWidget (переменные)
+ строку поиска + InlineColorEditor.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.frontend.widgets.primitives import TreeNavWidget
from multiprocess_prototype.registers.theme.schemas import THEME_VAR_TREE

from .inline_color_editor import InlineColorEditor

# Регулярка для проверки hex-цвета (#rrggbb)
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _build_flat_nav_tree(tree: dict[str, dict[str, list[str]]]) -> dict[str, list[str]]:
    """Конвертировать THEME_VAR_TREE в формат TreeNavWidget: {категория: [подкатегория, ...]}."""
    result: dict[str, list[str]] = {}
    for category, subcats in tree.items():
        result[category] = list(subcats.keys())
    return result


class VarsEditor(QWidget):
    """Редактор переменных темы: TreeNav + QTableWidget + поиск + InlineColorEditor.

    API:
        set_vars(var_names, values, descriptions)  -- заполнить таблицу
        collect_vars() -> dict[str, str]           -- собрать текущие значения
        close_color_editor()                       -- закрыть inline color editor
        update_color_preview(var_name, value)       -- обновить превью цвета

    Signals:
        var_changed(str, str)         -- (var_name, new_value) при изменении
        category_changed(str, str)    -- (category, subcategory) при навигации
    """

    var_changed = Signal(str, str)
    category_changed = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Текущие отображаемые имена переменных (для маппинга row -> var_name)
        self._displayed_var_names: list[str] = []
        # Текущие значения (для color preview и collect_vars)
        self._displayed_values: dict[str, str] = {}

        self._build_ui()

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_vars(
        self,
        var_names: list[str],
        values: dict[str, str],
        descriptions: dict[str, str],
    ) -> None:
        """Заполнить таблицу переменных указанным списком.

        Args:
            var_names: список имён переменных (порядок важен)
            values: {var_name: value}
            descriptions: {var_name: description}
        """
        self._displayed_var_names = list(var_names)
        self._displayed_values = dict(values)

        table = self._vars_table
        table.blockSignals(True)
        table.setRowCount(0)
        table.setRowCount(len(var_names))

        for row, var_name in enumerate(var_names):
            value = values.get(var_name, "")
            description = descriptions.get(var_name, "")

            # Колонка 0: Имя (не редактируемая)
            name_item = QTableWidgetItem(var_name)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            table.setItem(row, 0, name_item)

            # Колонка 1: Значение
            value_item = QTableWidgetItem(value)
            if _HEX_RE.match(value):
                # hex-цвета -- не редактируемые напрямую, клик откроет color editor
                value_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable,
                )
            else:
                # px/rgba/шрифты -- редактируемые по двойному клику
                value_item.setFlags(
                    Qt.ItemFlag.ItemIsEnabled
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEditable,
                )
            table.setItem(row, 1, value_item)

            # Колонка 2: Описание (не редактируемая)
            desc_item = QTableWidgetItem(description)
            desc_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            table.setItem(row, 2, desc_item)

            # Превью цвета
            self._set_color_preview(row, value)

        table.blockSignals(False)
        self._update_table_height()

    def collect_vars(self) -> dict[str, str]:
        """Собрать текущие значения переменных из таблицы.

        Для hex-переменных (с cellWidget) берёт значение из _displayed_values,
        для остальных -- из QTableWidgetItem.
        """
        result: dict[str, str] = {}
        table = self._vars_table
        for row in range(table.rowCount()):
            name_item = table.item(row, 0)
            if name_item is None:
                continue
            var_name = name_item.text()
            # Если есть cellWidget (color preview) -- значение из _displayed_values
            widget = table.cellWidget(row, 1)
            if widget is not None:
                result[var_name] = self._displayed_values.get(var_name, "")
            else:
                value_item = table.item(row, 1)
                if value_item is not None:
                    result[var_name] = value_item.text().strip()
        return result

    def close_color_editor(self) -> None:
        """Закрыть inline color editor (если открыт)."""
        if self._color_editor.is_open:
            self._color_editor.close()
            self._update_table_height()

    def update_color_preview(self, var_name: str, value: str) -> None:
        """Обновить превью цвета для переменной по имени."""
        self._displayed_values[var_name] = value
        # Найти строку переменной в таблице
        row = self._find_row_by_var_name(var_name)
        if row >= 0:
            self._set_color_preview(row, value)

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать GroupBox с поиском + TreeNav + таблица переменных."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        group = QGroupBox("Переменные темы")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(4, 4, 4, 4)
        group_layout.setSpacing(4)

        # Строка поиска
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Поиск переменных...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        group_layout.addWidget(self._search_input)

        # Горизонтальный layout: TreeNavWidget слева + QTableWidget справа
        nav_and_table = QHBoxLayout()
        nav_and_table.setSpacing(8)

        # Навигация (слева)
        self._nav = TreeNavWidget(nav_width=200)
        nav_tree = _build_flat_nav_tree(THEME_VAR_TREE)
        self._nav.set_tree(nav_tree)
        self._nav.leaf_selected.connect(self._on_subcategory_selected)
        self._nav.category_selected.connect(self._on_category_selected)
        nav_and_table.addWidget(self._nav)

        # Таблица переменных (справа)
        self._vars_table = QTableWidget(0, 3)
        self._vars_table.setHorizontalHeaderLabels(["Имя", "Значение", "Описание"])
        self._vars_table.setAlternatingRowColors(True)
        self._vars_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._vars_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._vars_table.verticalHeader().setVisible(False)
        self._vars_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        vh = self._vars_table.horizontalHeader()
        vh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        vh.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        vh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        vh.resizeSection(0, 180)
        vh.resizeSection(1, 160)

        # Сигналы таблицы
        self._vars_table.cellClicked.connect(self._on_cell_clicked)
        self._vars_table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self._vars_table.cellChanged.connect(self._on_cell_changed)

        nav_and_table.addWidget(self._vars_table, stretch=1)
        group_layout.addLayout(nav_and_table)
        layout.addWidget(group)

        # Inline color editor
        self._color_editor = InlineColorEditor(self)
        self._color_editor.color_changed.connect(self._on_color_live_changed)

    # ------------------------------------------------------------------
    # Обработчики таблицы переменных
    # ------------------------------------------------------------------

    def _on_cell_clicked(self, row: int, column: int) -> None:
        """Клик на ячейку -- для hex открыть/закрыть color editor."""
        editor = self._color_editor

        # Игнорировать клик на строке color editor
        if row == editor.editor_row:
            return

        # Клик на колонку «Значение» (1) для hex
        if column == 1:
            name_item = self._vars_table.item(row, 0)
            if name_item is None:
                return
            var_name = name_item.text()
            value = self._displayed_values.get(var_name, "")
            if _HEX_RE.match(value):
                # Если color editor уже открыт для этой строки -- закрыть
                if editor.is_open and editor.target_row == row:
                    self.close_color_editor()
                else:
                    editor.open(self._vars_table, row, var_name, value)
                    self._update_table_height()
                return

    def _on_cell_double_clicked(self, row: int, column: int) -> None:
        """Двойной клик -- inline edit для px/rgba/шрифтов (не для hex)."""
        if row == self._color_editor.editor_row:
            return
        if column != 1:
            return

        name_item = self._vars_table.item(row, 0)
        if name_item is None:
            return

        var_name = name_item.text()
        value = self._displayed_values.get(var_name, "")

        # Hex-цвета обрабатываются через color editor (по клику)
        if _HEX_RE.match(value):
            return

        # Для не-hex включить редактирование ячейки
        value_item = self._vars_table.item(row, 1)
        if value_item is not None:
            self._vars_table.editItem(value_item)

    def _on_cell_changed(self, row: int, column: int) -> None:
        """Редактирование ячейки в таблице -> эмитить var_changed."""
        if column != 1:
            return
        if row == self._color_editor.editor_row:
            return

        name_item = self._vars_table.item(row, 0)
        value_item = self._vars_table.item(row, 1)
        if name_item is None or value_item is None:
            return

        var_name = name_item.text()
        var_value = value_item.text().strip()
        self._displayed_values[var_name] = var_value
        self.var_changed.emit(var_name, var_value)

    def _on_color_live_changed(self, hex_color: str) -> None:
        """Color editor изменил цвет -> эмитить var_changed + обновить превью."""
        editor = self._color_editor
        if not editor.is_open:
            return
        var_name = editor.var_name
        self._displayed_values[var_name] = hex_color
        # Обновить превью в целевой строке
        target_row = editor.target_row
        if target_row >= 0:
            self._set_color_preview(target_row, hex_color)
        self.var_changed.emit(var_name, hex_color)

    # ------------------------------------------------------------------
    # Обработчики навигации
    # ------------------------------------------------------------------

    def _on_subcategory_selected(self, category: str, subcategory: str) -> None:
        """Клик по подкатегории в TreeNavWidget."""
        self.category_changed.emit(category, subcategory)

    def _on_category_selected(self, category: str) -> None:
        """Клик по категории в TreeNavWidget."""
        self.category_changed.emit(category, "")

    def _on_search_changed(self, text: str) -> None:
        """Фильтрация TreeNavWidget по тексту поиска."""
        if text.strip():
            self._nav.filter(text.strip())
        else:
            self._nav.clear_filter()

    # ------------------------------------------------------------------
    # Вспомогательные
    # ------------------------------------------------------------------

    def _set_color_preview(self, row: int, value: str) -> None:
        """Установить превью цвета в ячейке «Значение» для hex-значений."""
        table = self._vars_table
        if _HEX_RE.match(value):
            color = QColor(value)
            preview = QLabel()
            preview.setFixedSize(20, 20)
            palette = preview.palette()
            palette.setColor(QPalette.ColorRole.Window, color)
            preview.setPalette(palette)
            preview.setAutoFillBackground(True)
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(4, 2, 4, 2)
            container_layout.setSpacing(6)
            container_layout.addWidget(preview)
            label = QLabel(value)
            container_layout.addWidget(label)
            container_layout.addStretch()
            table.setCellWidget(row, 1, container)
        else:
            table.removeCellWidget(row, 1)

    def _update_table_height(self) -> None:
        """Пересчитать фиксированную высоту таблицы переменных."""
        table = self._vars_table
        header_h = table.horizontalHeader().height()
        row_count = table.rowCount()
        if row_count == 0:
            table.setFixedHeight(header_h + 40)
            return
        total_h = header_h + 4  # +4 margin
        for r in range(row_count):
            total_h += table.rowHeight(r)
        table.setFixedHeight(total_h)

    def _find_row_by_var_name(self, var_name: str) -> int:
        """Найти строку таблицы по имени переменной. -1 если не найдена."""
        table = self._vars_table
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is not None and item.text() == var_name:
                return row
        return -1
