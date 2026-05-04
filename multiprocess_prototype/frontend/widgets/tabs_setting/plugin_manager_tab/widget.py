"""Корневой виджет вкладки «Плагины» (MVP)."""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .models.plugin_manager_model import PluginManagerModel
from .plugin_catalog_table import PluginCatalogTable
from .plugin_detail_panel import PluginDetailPanel
from .presenter import PluginManagerPresenter


class PluginManagerTabWidget(QWidget):
    """Вкладка управления плагинами — реализует PluginManagerViewProtocol.

    Компоновка:
    - Toolbar со статусной строкой (сверху)
    - QSplitter: PluginCatalogTable (70%) + PluginDetailPanel (30%)
    """

    def __init__(
        self,
        plugin_manager: Any | None = None,
        command_handler: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать вкладку плагинов.

        Args:
            plugin_manager: PluginManager | None — для перезагрузки плагинов.
            command_handler: зарезервировано для IPC (MVP не используется).
            parent: родительский виджет.
        """
        super().__init__(parent)

        # Модель данных
        self._model = PluginManagerModel(
            plugin_manager=plugin_manager,
            command_handler=command_handler,
            parent=self,
        )

        # Построить UI-компоненты
        self._init_ui()

        # Презентер — создаётся после _init_ui чтобы виджеты уже существовали
        self._presenter = PluginManagerPresenter(
            view=self,
            model=self._model,
        )

        # Подключить Qt-сигналы к методам презентера
        self._connect_signals()

        # Подписаться на обновления модели
        self._model.plugins_updated.connect(self._presenter.on_model_updated)

        # Начальная загрузка данных
        self._presenter.on_init()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _init_ui(self) -> None:
        """Создать layout, toolbar и splitter с таблицей и панелью деталей."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Toolbar со статусной строкой
        self._toolbar = QToolBar()
        self._toolbar.setMovable(False)
        self._status_label = QLabel("Плагины: 0")
        self._toolbar.addWidget(self._status_label)
        layout.addWidget(self._toolbar)

        # Splitter: таблица слева (70%) + панель деталей справа (30%)
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = PluginCatalogTable(parent=self)
        self._detail = PluginDetailPanel(parent=self)

        self._splitter.addWidget(self._table)
        self._splitter.addWidget(self._detail)

        # Пропорции 70/30
        self._splitter.setStretchFactor(0, 7)
        self._splitter.setStretchFactor(1, 3)

        layout.addWidget(self._splitter)

    # ------------------------------------------------------------------
    # Подключение сигналов
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Подключить сигналы дочерних виджетов к методам презентера."""
        # Сигналы таблицы → presenter
        self._table.plugin_selected.connect(self._presenter.on_plugin_selected)
        self._table.plugin_enabled_changed.connect(self._presenter.on_plugin_enabled_changed)
        self._table.reload_requested.connect(self._presenter.on_reload_requested)

        # Изменение фильтра (поиск и категория) → presenter
        # Используем приватные виджеты таблицы — они надёжно существуют после _build_ui
        self._table._search_edit.textChanged.connect(
            lambda _: self._presenter.on_filter_changed()
        )
        self._table._category_combo.currentTextChanged.connect(
            lambda _: self._presenter.on_filter_changed()
        )

        # Сигнал панели деталей → presenter
        self._detail.default_config_changed.connect(self._presenter.on_default_config_changed)

    # ------------------------------------------------------------------
    # Реализация PluginManagerViewProtocol
    # ------------------------------------------------------------------

    def refresh_table(self, plugins: list[dict]) -> None:
        """Обновить таблицу каталога плагинов.

        Args:
            plugins: список dict плагинов (Dict at Boundary).
        """
        self._table.set_data(plugins)

    def show_plugin_detail(self, detail: dict) -> None:
        """Показать детали выбранного плагина в правой панели.

        Args:
            detail: dict из get_plugin_detail().
        """
        self._detail.show_plugin(detail)

    def clear_detail(self) -> None:
        """Очистить правую панель деталей."""
        self._detail.clear()

    def set_status_text(self, text: str) -> None:
        """Установить текст в статусной строке toolbar.

        Args:
            text: текст для отображения.
        """
        self._status_label.setText(text)

    def show_warning(self, title: str, text: str) -> None:
        """Показать предупреждение пользователю.

        Args:
            title: заголовок диалога.
            text: текст предупреждения.
        """
        QMessageBox.warning(self, title, text)

    def get_current_filter(self) -> tuple[str | None, str]:
        """Текущий фильтр из таблицы.

        Returns:
            Кортеж (category, search_text), где category=None означает "Все".
        """
        return self._table.current_filter()
