# -*- coding: utf-8 -*-
"""
BaseAdminPanel — базовый класс для admin-панелей с таблицей.

Извлекает общий паттерн:
  - заголовок (QLabel с objectName="PanelHeader")
  - QTableWidget с конфигурацией из _TABLE_COLUMNS
  - метод action_buttons() для action-колонки
  - метод _fill_table() для заполнения данных

Подклассы:
  - определяют _TABLE_COLUMNS: list[tuple[str, str, int]]
  - определяют _HEADER_TITLE: str
  - переопределяют _fill_table() для заполнения данных
  - создают кнопки и возвращают через action_buttons()
"""
from __future__ import annotations

from typing import ClassVar

from PySide6.QtWidgets import (
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)


class BaseAdminPanel(QWidget):
    """Базовый класс для admin-панелей с таблицей.

    Класс-переменные для подклассов:
        _TABLE_COLUMNS: список (key, title, width) — определение колонок
        _HEADER_TITLE:  заголовок панели (отображается в header)

    Подклассы вызывают _init_table() в своём _setup_ui() после
    создания root layout, затем добавляют свои элементы.
    """

    _TABLE_COLUMNS: ClassVar[list[tuple[str, str, int]]] = []
    _HEADER_TITLE: ClassVar[str] = ""

    def _create_header(self, parent_layout: QVBoxLayout) -> None:
        """Добавить стандартный заголовок панели в layout."""
        header_layout = QHBoxLayout()
        header_label = QLabel(self._HEADER_TITLE)
        header_label.setObjectName("PanelHeader")
        header_layout.addWidget(header_label)
        header_layout.addStretch()
        parent_layout.addLayout(header_layout)

    def _create_table(self) -> QTableWidget:
        """Создать и настроить QTableWidget по _TABLE_COLUMNS.

        Возвращает таблицу (не добавляет в layout — подкласс решает где).
        Последняя колонка растягивается, остальные — Interactive с заданной шириной.
        """
        column_titles = [col[1] for col in self._TABLE_COLUMNS]
        column_widths = [col[2] for col in self._TABLE_COLUMNS]

        table = QTableWidget(0, len(self._TABLE_COLUMNS))
        table.setHorizontalHeaderLabels(column_titles)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)

        h = table.horizontalHeader()
        for i, width in enumerate(column_widths):
            if i == len(column_widths) - 1:
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
            else:
                table.setColumnWidth(i, width)
                h.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)

        return table

    def action_buttons(self) -> list[QPushButton]:
        """Кнопки действий для action-колонки. Переопределить в подклассе."""
        return []

    @property
    def column_keys(self) -> list[str]:
        """Список ключей колонок (первый элемент каждого кортежа)."""
        return [col[0] for col in self._TABLE_COLUMNS]
