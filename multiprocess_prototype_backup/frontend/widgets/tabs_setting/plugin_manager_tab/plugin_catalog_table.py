# multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/plugin_catalog_table.py
"""PluginCatalogTable — таблица каталога плагинов с фильтрацией и поиском.

Отображает список плагинов из PluginRegistry. Поддерживает:
- Поиск по имени плагина
- Фильтрацию по категории (source / processing / output / все)
- Toggle включён/выключен через чекбокс
- Выбор плагина для просмотра деталей
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

_logger = logging.getLogger(__name__)

# Индексы колонок таблицы
_COL_ENABLED = 0
_COL_NAME = 1
_COL_CATEGORY = 2
_COL_DESCRIPTION = 3
_COL_PORTS = 4

# Заголовки колонок
_COLUMN_HEADERS = ["Вкл", "Имя", "Категория", "Описание", "Порты"]

# Категории для комбобокса
_CATEGORIES = ["Все", "source", "processing", "output"]


class PluginCatalogTable(QWidget):
    """Таблица каталога плагинов с панелью фильтрации.

    Сигналы:
        plugin_selected(str): пользователь выбрал плагин (имя плагина)
        plugin_enabled_changed(str, bool): пользователь изменил чекбокс включения
        reload_requested(): пользователь нажал кнопку "Обновить"
    """

    plugin_selected = Signal(str)
    plugin_enabled_changed = Signal(str, bool)
    reload_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Инициализировать таблицу каталога плагинов.

        Args:
            parent: родительский виджет.
        """
        super().__init__(parent)

        # Внутреннее состояние — имена плагинов по строкам таблицы
        self._row_plugin_names: list[str] = []
        self._item_changed_connected = False

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать layout и дочерние виджеты."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Панель инструментов: поиск + фильтр по категории + кнопка обновления
        toolbar = self._build_toolbar()
        layout.addLayout(toolbar)

        # Таблица плагинов
        self._table = self._build_table()
        layout.addWidget(self._table)

    def _build_toolbar(self) -> QHBoxLayout:
        """Создать горизонтальную панель инструментов.

        Returns:
            QHBoxLayout с полем поиска, комбобоксом категорий и кнопкой обновления.
        """
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # Поле поиска по имени
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Поиск по имени...")
        toolbar.addWidget(self._search_edit)

        # Метка + комбобокс категории
        toolbar.addWidget(QLabel("Категория:"))
        self._category_combo = QComboBox()
        self._category_combo.addItems(_CATEGORIES)
        toolbar.addWidget(self._category_combo)

        # Кнопка обновить
        self._reload_btn = QPushButton("Обновить")
        toolbar.addWidget(self._reload_btn)

        return toolbar

    def _build_table(self) -> QTableWidget:
        """Создать и настроить QTableWidget.

        Returns:
            Настроенный экземпляр QTableWidget.
        """
        table = QTableWidget(0, len(_COLUMN_HEADERS))
        table.setHorizontalHeaderLabels(_COLUMN_HEADERS)

        # Режимы выделения — строки целиком, одна за раз
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        # Запрет редактирования (данные только для чтения, кроме чекбокса)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        # Растянуть последнюю колонку
        table.horizontalHeader().setStretchLastSection(True)

        # Скрыть вертикальные заголовки (номера строк)
        table.verticalHeader().setVisible(False)

        return table

    # ------------------------------------------------------------------
    # Подключение сигналов
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Подключить сигналы виджетов к слотам."""
        self._search_edit.textChanged.connect(self._on_search_changed)
        self._category_combo.currentTextChanged.connect(self._on_filter_changed)
        self._reload_btn.clicked.connect(self.reload_requested)
        self._table.cellClicked.connect(self._on_row_clicked)

    # ------------------------------------------------------------------
    # Публичные методы
    # ------------------------------------------------------------------

    def set_data(self, plugins: list[dict]) -> None:
        """Заполнить таблицу из списка словарей плагинов.

        Использует blockSignals чтобы не вызывать промежуточные сигналы
        во время программного заполнения.

        Args:
            plugins: list[dict] с полями name, category, description,
                     inputs, outputs, enabled.
        """
        # Блокируем сигналы таблицы во время заполнения
        self._table.blockSignals(True)
        try:
            self._row_plugin_names = []
            self._table.setRowCount(0)

            for plugin in plugins:
                row = self._table.rowCount()
                self._table.insertRow(row)

                name = plugin.get("name", "")
                self._row_plugin_names.append(name)

                # Колонка "Вкл" — чекбокс
                enabled_item = QTableWidgetItem()
                check_state = Qt.CheckState.Checked if plugin.get("enabled", True) else Qt.CheckState.Unchecked
                enabled_item.setCheckState(check_state)
                enabled_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, _COL_ENABLED, enabled_item)

                # Колонка "Имя"
                self._table.setItem(row, _COL_NAME, QTableWidgetItem(name))

                # Колонка "Категория"
                category = plugin.get("category", "")
                self._table.setItem(row, _COL_CATEGORY, QTableWidgetItem(category))

                # Колонка "Описание"
                description = plugin.get("description", "")
                self._table.setItem(row, _COL_DESCRIPTION, QTableWidgetItem(description))

                # Колонка "Порты" — формат I/O
                inputs = plugin.get("inputs", 0)
                outputs = plugin.get("outputs", 0)
                self._table.setItem(row, _COL_PORTS, QTableWidgetItem(f"{inputs}/{outputs}"))

        finally:
            self._table.blockSignals(False)

        # Подключаем обработчик чекбоксов после заполнения
        # (используем itemChanged — cellClicked не ловит изменение чекбокса клавиатурой)
        if self._item_changed_connected:
            self._table.itemChanged.disconnect(self._on_item_changed)
        self._table.itemChanged.connect(self._on_item_changed)
        self._item_changed_connected = True

    def current_filter(self) -> tuple[str | None, str]:
        """Вернуть текущие значения фильтра.

        Returns:
            Кортеж (category, search), где category=None означает "Все".
        """
        raw_category = self._category_combo.currentText()
        category = None if raw_category == "Все" else raw_category
        search = self._search_edit.text()
        return category, search

    # ------------------------------------------------------------------
    # Слоты
    # ------------------------------------------------------------------

    def _on_search_changed(self, text: str) -> None:
        """Обработать изменение текста в поле поиска.

        Args:
            text: текущий текст поиска (не используется — модель читает через current_filter).
        """
        # Оставляем реакцию на стороне владельца — он сам вызовет filter_plugins + set_data
        _logger.debug("Поиск изменён: '%s'", text)

    def _on_filter_changed(self, category: str) -> None:
        """Обработать изменение выбранной категории.

        Args:
            category: текст выбранного элемента комбобокса.
        """
        _logger.debug("Фильтр категории изменён: '%s'", category)

    def _on_row_clicked(self, row: int, col: int) -> None:
        """Обработать клик по ячейке таблицы.

        Если кликнули НЕ на чекбокс — эмитируем plugin_selected.

        Args:
            row: индекс строки.
            col: индекс колонки.
        """
        if col == _COL_ENABLED:
            # Клик по колонке чекбокса обрабатывается в _on_item_changed
            return

        if 0 <= row < len(self._row_plugin_names):
            plugin_name = self._row_plugin_names[row]
            _logger.debug("Выбран плагин: '%s'", plugin_name)
            self.plugin_selected.emit(plugin_name)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Обработать изменение элемента таблицы.

        Реагирует только на изменение чекбокса в колонке "Вкл".

        Args:
            item: изменённый элемент таблицы.
        """
        if item.column() != _COL_ENABLED:
            return

        row = item.row()
        if 0 <= row < len(self._row_plugin_names):
            plugin_name = self._row_plugin_names[row]
            enabled = item.checkState() == Qt.CheckState.Checked
            _logger.debug("Чекбокс плагина '%s' изменён: %s", plugin_name, enabled)
            self.plugin_enabled_changed.emit(plugin_name, enabled)
