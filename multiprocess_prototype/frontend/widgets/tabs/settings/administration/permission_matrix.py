# -*- coding: utf-8 -*-
"""PermissionMatrix — read-only матрица прав для выбранной роли.

Строки = уникальные ресурсы из списка permissions роли.
Колонки: «Ресурс» | «View» | «Edit».

В PR2 все чекбоксы disabled (режим только чтение).
Активация редактирования — PR4.
"""
from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class PermissionMatrix(QWidget):
    """Read-only матрица permissions: строки = ресурсы, колонки = View / Edit.

    В PR2 все чекбоксы disabled (read-only).
    Данные загружаются через set_role(role_dict).

    Структура отображения:
      ┌──────────────────┬──────┬──────┐
      │ Ресурс           │ View │ Edit │
      ├──────────────────┼──────┼──────┤
      │ tabs.recipes     │  ✓   │  ✓   │
      │ tabs.pipeline    │  ✓   │      │
      │ ...              │      │      │
      └──────────────────┴──────┴──────┘
    """

    # Индексы колонок
    _COL_RESOURCE = 0
    _COL_VIEW = 1
    _COL_EDIT = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._table = QTableWidget(0, 3, self)
        self._table.setHorizontalHeaderLabels(["Ресурс", "View", "Edit"])

        # Колонка «Ресурс» растягивается, View/Edit — фиксированные
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(self._COL_RESOURCE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self._COL_VIEW, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self._COL_EDIT, QHeaderView.ResizeMode.ResizeToContents)

        # Минимальная ширина колонок View/Edit
        self._table.setColumnWidth(self._COL_VIEW, 60)
        self._table.setColumnWidth(self._COL_EDIT, 60)

        # Скрыть вертикальные заголовки (номера строк)
        self._table.verticalHeader().setVisible(False)

        # Read-only: запретить редактирование и выделение
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def set_role(self, role_dict: dict) -> None:
        """Отобразить permissions роли в матрице. Все чекбоксы disabled.

        Алгоритм:
          - Из permissions строк формата «ресурс.action» выделить ресурс
            (всё до последней точки) и action (последний сегмент).
          - Каждый уникальный ресурс — одна строка.
          - Колонки View/Edit — чекбоксы по наличию action «view»/«edit».
          - Строки отсортированы по алфавиту имени ресурса.
        """
        self._table.setRowCount(0)

        # Группируем actions по ресурсам
        buckets: dict[str, set[str]] = defaultdict(set)
        for perm in role_dict.get("permissions", []):
            if "." not in perm:
                continue
            resource, _, action = perm.rpartition(".")
            buckets[resource].add(action)

        # Заполняем строки таблицы (по алфавиту)
        for resource in sorted(buckets.keys()):
            actions = buckets[resource]
            row = self._table.rowCount()
            self._table.insertRow(row)

            # Колонка «Ресурс» — текстовая ячейка
            resource_item = QTableWidgetItem(resource)
            resource_item.setFlags(resource_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, self._COL_RESOURCE, resource_item)

            # Колонки «View» и «Edit» — чекбоксы
            self._table.setCellWidget(
                row, self._COL_VIEW,
                self._make_checkbox("view" in actions),
            )
            self._table.setCellWidget(
                row, self._COL_EDIT,
                self._make_checkbox("edit" in actions),
            )

    def clear(self) -> None:
        """Очистить матрицу (убрать все строки)."""
        self._table.setRowCount(0)

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    @staticmethod
    def _make_checkbox(checked: bool) -> QWidget:
        """Создать QCheckBox, центрированный внутри QWidget (паттерн для setCellWidget).

        Чекбокс disabled — матрица read-only в PR2.
        """
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        checkbox = QCheckBox()
        checkbox.setChecked(checked)
        checkbox.setEnabled(False)  # read-only режим (PR2)

        layout.addWidget(checkbox)
        return container
