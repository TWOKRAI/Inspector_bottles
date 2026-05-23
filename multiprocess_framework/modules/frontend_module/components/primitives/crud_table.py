"""Таблица с CRUD-операциями: Add/Remove строк.

Виджет не знает об AppContext — принимает чистые данные,
не импортирует ничего из multiprocess_prototype.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


__all__ = ["CrudTable"]


class CrudTable(QWidget):
    """Таблица с CRUD-операциями: Add/Remove строк.

    Универсальная таблица для любых табличных данных.
    """

    # Сигнал: добавлена новая строка
    row_added = Signal()
    # Сигнал: удалена строка (индекс удалённой строки)
    row_removed = Signal(int)
    # Сигнал: изменился выбор (индекс строки, -1 если ничего не выбрано)
    selection_changed = Signal(int)

    def __init__(self, columns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._columns = list(columns)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(4)

        # --- Таблица ---
        self._table = QTableWidget(0, len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setStretchLastSection(True)
        root_layout.addWidget(self._table, stretch=1)

        # --- Ряд кнопок ---
        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)

        self._add_btn = QPushButton("Добавить")
        self._remove_btn = QPushButton("Удалить")

        button_row.addWidget(self._add_btn)
        button_row.addWidget(self._remove_btn)
        button_row.addStretch()

        root_layout.addLayout(button_row)

        # Подключить сигналы
        self._add_btn.clicked.connect(self._on_add_clicked)
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_data(self, rows: list[list[str]]) -> None:
        """Полностью заменить данные таблицы.

        Args:
            rows: список строк, каждая строка — список строковых значений.
        """
        self._table.setRowCount(0)
        for row_values in rows:
            self._insert_row(row_values)

    def add_row(self, values: list[str]) -> int:
        """Добавить строку в конец таблицы.

        Args:
            values: список строковых значений для ячеек.

        Returns:
            Индекс добавленной строки.
        """
        row_index = self._insert_row(values)
        self.row_added.emit()
        return row_index

    def remove_selected(self) -> None:
        """Удалить выбранную строку."""
        row = self.selected_row()
        if row == -1:
            return
        self._table.removeRow(row)
        self.row_removed.emit(row)

    def selected_row(self) -> int:
        """Вернуть индекс выбранной строки или -1."""
        indexes = self._table.selectedIndexes()
        if not indexes:
            return -1
        return indexes[0].row()

    def row_count(self) -> int:
        """Вернуть количество строк в таблице."""
        return self._table.rowCount()

    def get_cell_widget(self, row: int, col: int) -> QWidget | None:
        """Получить виджет ячейки.

        Args:
            row: индекс строки.
            col: индекс столбца.

        Returns:
            QWidget или None, если виджет не установлен.
        """
        return self._table.cellWidget(row, col)

    def set_cell_widget(self, row: int, col: int, widget: QWidget) -> None:
        """Установить виджет в ячейку.

        Args:
            row:    индекс строки.
            col:    индекс столбца.
            widget: виджет для установки.
        """
        self._table.setCellWidget(row, col, widget)

    def set_add_enabled(self, enabled: bool) -> None:
        """Включить / отключить кнопку «Добавить»."""
        self._add_btn.setEnabled(enabled)

    def set_remove_enabled(self, enabled: bool) -> None:
        """Включить / отключить кнопку «Удалить»."""
        self._remove_btn.setEnabled(enabled)

    def get_row_data(self, row: int) -> list[str]:
        """Получить данные строки как список строк.

        Args:
            row: индекс строки.

        Returns:
            Список строковых значений ячеек (только QTableWidgetItem, не виджеты).
        """
        result: list[str] = []
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            result.append(item.text() if item is not None else "")
        return result

    # ------------------------------------------------------------------
    # Внутренняя логика
    # ------------------------------------------------------------------

    def _insert_row(self, values: list[str]) -> int:
        """Вставить строку в конец таблицы без emit сигналов.

        Returns:
            Индекс вставленной строки.
        """
        row_index = self._table.rowCount()
        self._table.insertRow(row_index)
        for col, value in enumerate(values):
            if col < self._table.columnCount():
                self._table.setItem(row_index, col, QTableWidgetItem(value))
        return row_index

    def _on_add_clicked(self) -> None:
        """Обработчик нажатия «Добавить»: вставить пустую строку."""
        empty_values = [""] * len(self._columns)
        self._insert_row(empty_values)
        self.row_added.emit()

    def _on_remove_clicked(self) -> None:
        """Обработчик нажатия «Удалить»: удалить выбранную строку."""
        self.remove_selected()

    def _on_selection_changed(self) -> None:
        """Обработчик изменения выбора в таблице."""
        self.selection_changed.emit(self.selected_row())
