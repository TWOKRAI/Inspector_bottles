# -*- coding: utf-8 -*-
"""HistorySection — секция «История» для Settings таба.

Реализует:
- SectionProtocol   — интерфейс секции (key, title, widget, action_buttons, on_activated)
- HistoryView       — интерфейс вью для HistoryPresenter (set_table_data, set_save_enabled, ...)

Структура UI:
    QWidget (container)
      └── QVBoxLayout
            └── QTableWidget  3 колонки: Время, Тип, Описание (G.4.4 domain history)

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

if TYPE_CHECKING:
    from .presenter import HistoryPresenter
    from multiprocess_prototype.domain.app_services import AppServices

# Заголовки колонок таблицы истории (G.4.4: domain HistoryEntry)
_HISTORY_COLUMNS = ["Время", "Тип", "Описание"]


class HistorySection(QWidget):
    """Секция «История» — таблица действий ActionBus + кнопки CSV-экспорта.

    Реализует SectionProtocol и HistoryView — presenter вызывает view-методы
    напрямую на объекте секции.

    Task D.5: принимает services: AppServices вместо ctx: AppContext.
    HistorySection сам по себе не использует services — presenter инжектируется
    через set_presenter() из BaseTreeNavTab._apply_presenter_factory.
    Параметр services сохранён для потенциального расширения (Phase E).
    """

    def __init__(
        self,
        services: "AppServices | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._services = services
        # Presenter инжектируется позже через set_presenter() — до этого None.
        # Первый refresh() произойдёт при on_activated() после inject'а.
        self._presenter: "HistoryPresenter | None" = None
        self._build_ui()

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
        if self._presenter is not None:
            self._presenter.refresh()

    def on_deactivated(self) -> None:
        """Ничего не делаем при уходе с секции."""

    # ------------------------------------------------------------------
    # HistoryView Protocol
    # ------------------------------------------------------------------

    def set_table_data(self, rows: list[tuple[str, str, str]]) -> None:
        """Заполнить таблицу строками (Время, Тип, Описание) из presenter'а."""
        self._table.setRowCount(len(rows))
        for row_idx, (ts, command_type, label) in enumerate(rows):
            self._table.setItem(row_idx, 0, QTableWidgetItem(ts))
            self._table.setItem(row_idx, 1, QTableWidgetItem(command_type))
            self._table.setItem(row_idx, 2, QTableWidgetItem(label))

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
        return self._presenter.refresh if self._presenter is not None else None

    # ------------------------------------------------------------------
    # Публичный аксессор presenter'а (для подписки из tab.py)
    # ------------------------------------------------------------------

    @property
    def presenter(self) -> "HistoryPresenter | None":
        """Вернуть presenter секции (для подписки refresh на ActionBus)."""
        return self._presenter

    def set_presenter(self, presenter: "HistoryPresenter") -> None:
        """Инжектировать presenter в секцию.

        HistoryPresenter не требует явного initialize() — данные загружаются
        при первом on_activated() через refresh().

        ВАЖНО: вызывается из BaseTreeNavTab._apply_presenter_factory ПЕРЕД
        _connect_section_events, чтобы bus_change_callback() уже возвращал
        валидный callable.
        """
        self._presenter = presenter

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
            h.resizeSection(0, 140)  # Время
            h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
            h.resizeSection(1, 180)  # Тип команды
            h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Описание — растягивается

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
        """Делегировать сохранение CSV presenter'у (guard на случай None)."""
        if self._presenter is not None:
            self._presenter.save_to_csv()

    def _on_clear_clicked(self) -> None:
        """Делегировать очистку истории presenter'у (guard на случай None)."""
        if self._presenter is not None:
            self._presenter.clear()
