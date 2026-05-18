# -*- coding: utf-8 -*-
"""HistorySection — секция «История» для Settings таба.

Реализует:
- SectionProtocol   — интерфейс секции (key, title, widget, action_buttons, on_activated)
- HistoryView       — интерфейс вью для HistoryPresenter (set_table_data, set_save_enabled, ...)

Структура UI:
    QWidget (container)
      └── QVBoxLayout
            └── QTableWidget  4 колонки: Время, Вкладка, Параметр, Значение

Кнопки «Сохранить в файл» и «Очистить историю» возвращаются через action_buttons()
и регистрируются в action-колонке SettingsTab.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .presenter import HistoryPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

# Заголовки колонок таблицы истории
_HISTORY_COLUMNS = ["Время", "Вкладка", "Параметр", "Значение"]


class HistorySection(QWidget):
    """Секция «История» — таблица действий ActionBus + кнопки CSV-экспорта.

    Реализует SectionProtocol и HistoryView — presenter вызывает view-методы
    напрямую на объекте секции.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._build_ui()
        self._presenter = HistoryPresenter(view=self, rm=None, ui=None, ctx=ctx)

    # ------------------------------------------------------------------
    # SectionProtocol
    # ------------------------------------------------------------------

    @property
    def key(self) -> str:
        """Уникальный идентификатор секции."""
        return "history"

    @property
    def title(self) -> str:
        """Отображаемое название секции."""
        return "История"

    def widget(self) -> QWidget:
        """Корневой QWidget секции."""
        return self

    def action_buttons(self) -> list[QWidget]:
        """Кнопки для action-колонки."""
        return [self._btn_save, self._btn_clear]

    def on_activated(self) -> None:
        """Обновить таблицу при переключении на секцию."""
        self._presenter.refresh()

    def on_deactivated(self) -> None:
        """Ничего не делаем при уходе с секции."""

    # ------------------------------------------------------------------
    # HistoryView Protocol
    # ------------------------------------------------------------------

    def set_table_data(self, rows: list[tuple[str, str, str, str]]) -> None:
        """Заполнить таблицу строками из presenter'а."""
        self._table.setRowCount(len(rows))
        for row_idx, (ts, tab_name, param, value) in enumerate(rows):
            self._table.setItem(row_idx, 0, QTableWidgetItem(ts))
            self._table.setItem(row_idx, 1, QTableWidgetItem(tab_name))
            self._table.setItem(row_idx, 2, QTableWidgetItem(param))
            self._table.setItem(row_idx, 3, QTableWidgetItem(value))

    def set_save_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки «Сохранить в файл»."""
        self._btn_save.setEnabled(enabled)

    def set_clear_enabled(self, enabled: bool) -> None:
        """Установить доступность кнопки «Очистить историю»."""
        self._btn_clear.setEnabled(enabled)

    def scroll_to_bottom(self) -> None:
        """Прокрутить таблицу к последней строке."""
        self._table.scrollToBottom()

    def get_save_path(self) -> str | None:
        """Показать диалог сохранения файла и вернуть путь (или None если отменено)."""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить историю",
            "history.csv",
            "CSV (*.csv);;Все файлы (*)",
        )
        return path if path else None

    def bus_change_callback(self) -> "Callable[[], None] | None":
        """Вернуть колбэк для подписки на изменения ActionBus (SectionWithEvents)."""
        return self._presenter.refresh

    # ------------------------------------------------------------------
    # Публичный аксессор presenter'а (для подписки из tab.py)
    # ------------------------------------------------------------------

    @property
    def presenter(self) -> HistoryPresenter:
        """Вернуть presenter секции (для подписки refresh на ActionBus)."""
        return self._presenter

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать таблицу истории и кнопки."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        group = QGroupBox("История")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        outer.addWidget(group)

        # Таблица истории
        self._table = QTableWidget(0, len(_HISTORY_COLUMNS))
        self._table.setHorizontalHeaderLabels(_HISTORY_COLUMNS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        # Скроллом управляет мастер-скроллбар DiffScrollTabLayout
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._table.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents,
        )
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        h = self._table.horizontalHeader()
        if h:
            h.setStretchLastSection(False)
            h.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
            h.resizeSection(0, 140)  # Время — пошире
            h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            h.resizeSection(1, 150)  # Вкладка — пошире
            h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
            h.resizeSection(3, 120)  # Значение — поуже

        layout.addWidget(self._table)

        # Кнопки (регистрируются в action-колонке через action_buttons())
        self._btn_save = QPushButton("Сохранить в файл")
        self._btn_save.setToolTip("Экспортировать историю в CSV-файл")
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self._on_save_clicked)

        self._btn_clear = QPushButton("Очистить историю")
        self._btn_clear.setToolTip("Очистить всю историю действий")
        self._btn_clear.setEnabled(False)
        self._btn_clear.clicked.connect(self._on_clear_clicked)

    # ------------------------------------------------------------------
    # Слоты кнопок
    # ------------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        """Делегировать сохранение CSV presenter'у."""
        self._presenter.save_to_csv()

    def _on_clear_clicked(self) -> None:
        """Делегировать очистку истории presenter'у."""
        self._presenter.clear()
