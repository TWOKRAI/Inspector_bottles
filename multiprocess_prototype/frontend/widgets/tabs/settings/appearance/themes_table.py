# -*- coding: utf-8 -*-
"""ThemesTable -- QTableWidget с таблицей тем оформления.

Чистый table-виджет без бизнес-логики.
Колонки: Название | Тип | Родительская.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# Пустые строки внизу таблицы для визуального запаса
_EMPTY_ROWS = 3


class ThemesTable(QWidget):
    """Таблица тем оформления (Название | Тип | Родительская).

    API:
        set_themes(themes)      -- заполнить таблицу
        select_by_name(name)    -- выбрать строку по имени

    Signals:
        theme_selected(str, bool)  -- (name, is_default) при выборе строки
    """

    theme_selected = Signal(str, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_themes(self, themes: list[tuple[str, str, str]]) -> None:
        """Заполнить таблицу темами: [(name, kind, parent), ...].

        Добавляет _EMPTY_ROWS пустых строк внизу для визуального запаса.
        """
        table = self._table
        table.blockSignals(True)
        table.setRowCount(0)
        table.setRowCount(len(themes) + _EMPTY_ROWS)

        for row, (name, kind, parent_name) in enumerate(themes):
            name_item = QTableWidgetItem(name)
            kind_item = QTableWidgetItem(kind)
            parent_item = QTableWidgetItem(parent_name)

            # default-темы -- серый текст в колонках «Тип» и «Родительская»
            if kind == "default":
                gray = QBrush(QColor("#888888"))
                kind_item.setForeground(gray)
                parent_item.setForeground(gray)

            table.setItem(row, 0, name_item)
            table.setItem(row, 1, kind_item)
            table.setItem(row, 2, parent_item)

        table.blockSignals(False)
        self._update_height()

        # Выбрать первую строку по умолчанию
        if table.rowCount() > 0:
            table.selectRow(0)

    def select_by_name(self, name: str) -> None:
        """Найти и выбрать строку по имени темы."""
        table = self._table
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is not None and item.text() == name:
                table.selectRow(row)
                return

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать GroupBox с QTableWidget."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        group = QGroupBox("Темы")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(4, 4, 4, 4)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Название", "Тип", "Родительская"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.verticalHeader().setVisible(False)

        # Пропорции колонок
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setStretchLastSection(False)
        h.setMinimumSectionSize(40)
        self._table.setColumnWidth(0, 200)
        self._table.setColumnWidth(1, 100)
        self._table.setColumnWidth(2, 200)

        # Сигнал выбора строки
        self._table.currentCellChanged.connect(self._on_cell_changed)

        group_layout.addWidget(self._table)
        layout.addWidget(group)

    # ------------------------------------------------------------------
    # Внутренние обработчики
    # ------------------------------------------------------------------

    def _on_cell_changed(
        self,
        current_row: int,
        _current_col: int,
        _prev_row: int,
        _prev_col: int,
    ) -> None:
        """Смена текущей строки -> эмитить theme_selected(name, is_default)."""
        if current_row < 0:
            return
        name_item = self._table.item(current_row, 0)
        kind_item = self._table.item(current_row, 1)
        if name_item is None:
            return
        name = name_item.text()
        is_default = kind_item is not None and kind_item.text() == "default"
        self.theme_selected.emit(name, is_default)

    def _update_height(self) -> None:
        """Установить фиксированную высоту таблицы по числу строк."""
        table = self._table
        header_h = table.horizontalHeader().height()
        row_count = table.rowCount()
        row_h = table.rowHeight(0) if row_count > 0 else 30
        total = header_h + row_count * row_h + 4  # +4 margin
        table.setFixedHeight(total)
