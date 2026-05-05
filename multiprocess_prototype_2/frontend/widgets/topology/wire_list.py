"""WireListWidget — таблица связей (wires) с кнопками Add / Remove."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class WireListWidget(QWidget):
    """Виджет таблицы wires.

    Колонки: Source | Target | Description
    Кнопки Add/Remove генерируют соответствующие сигналы.
    """

    # Пользователь нажал Add (запрос на добавление нового wire)
    wire_add_requested = Signal()
    # Пользователь нажал Remove (индекс строки)
    wire_remove_requested = Signal(int)

    _COLUMNS = ["Source", "Target", "Description"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        """Построить UI виджета."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Таблица wires
        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

        # Кнопки
        btn_layout = QHBoxLayout()
        self._btn_add = QPushButton("Add Wire")
        self._btn_remove = QPushButton("Remove Wire")
        self._btn_remove.setEnabled(False)
        self._btn_add.clicked.connect(self.wire_add_requested)
        self._btn_remove.clicked.connect(self._on_remove_clicked)
        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_remove)
        layout.addLayout(btn_layout)

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def refresh(self, wires: list) -> None:
        """Обновить таблицу wires.

        Принимает list[Wire] (объекты с атрибутами source/target/description)
        или list[dict] с теми же ключами.
        """
        self._table.blockSignals(True)
        self._table.setRowCount(0)

        for wire in wires:
            # Поддержка как Wire-объектов, так и dict
            if isinstance(wire, dict):
                source = wire.get("source", "")
                target = wire.get("target", "")
                description = wire.get("description", "")
            else:
                source = getattr(wire, "source", "")
                target = getattr(wire, "target", "")
                description = getattr(wire, "description", "")

            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(source))
            self._table.setItem(row, 1, QTableWidgetItem(target))
            self._table.setItem(row, 2, QTableWidgetItem(description))

        self._table.blockSignals(False)
        self._btn_remove.setEnabled(False)

    def selected_row(self) -> int:
        """Индекс выбранной строки или -1."""
        rows = self._table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    # ------------------------------------------------------------------ #
    #  Приватные слоты                                                     #
    # ------------------------------------------------------------------ #

    def _on_selection_changed(self) -> None:
        """Слот: изменилось выделение в таблице."""
        has_selection = self.selected_row() >= 0
        self._btn_remove.setEnabled(has_selection)

    def _on_remove_clicked(self) -> None:
        """Слот: нажата кнопка Remove Wire."""
        row = self.selected_row()
        if row >= 0:
            self.wire_remove_requested.emit(row)
