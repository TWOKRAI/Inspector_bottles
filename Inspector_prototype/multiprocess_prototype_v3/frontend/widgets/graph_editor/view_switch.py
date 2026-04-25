"""ViewSwitchWidget — переключатель между табличным и графовым представлением."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .catalog_palette import CatalogPalette
from .graph_scene import GraphScene
from .graph_view import GraphView
from .linearity_check import get_linearity_warning


class ViewSwitchWidget(QWidget):
    """Контейнер с переключением между табличным и графовым view.

    В табличном виде при нелинейном графе показывает жёлтое предупреждение.
    В графовом виде загружает все узлы и связи через GraphScene.load_graph().

    Сигналы:
        view_changed(str): "table" или "graph" — при смене вида.
    """

    view_changed = Signal(str)

    def __init__(self, table_widget: QWidget | None = None, parent=None):
        super().__init__(parent)

        self._current_mode = "table"

        # --- Основной layout ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Toolbar с кнопкой переключения ---
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)

        self._switch_btn = QToolButton()
        self._switch_btn.setText("Граф")
        self._switch_btn.setToolTip("Переключить на графовый вид")
        self._switch_btn.setCheckable(True)
        self._switch_btn.toggled.connect(self._on_switch)
        toolbar.addWidget(self._switch_btn)

        toolbar.addStretch()
        main_layout.addLayout(toolbar)

        # --- Предупреждение о нелинейности графа ---
        self._warning_label = QLabel()
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(
            "background-color: #FFF3CD; color: #856404; "
            "padding: 6px; border: 1px solid #FFEEBA; border-radius: 3px;"
        )
        self._warning_label.hide()
        main_layout.addWidget(self._warning_label)

        # --- Стек: страница таблицы / страница графа ---
        self._stack = QStackedWidget()

        # Страница 0: табличное представление (placeholder если не передан виджет)
        self._table_widget = table_widget or QLabel("Табличное представление")
        self._stack.addWidget(self._table_widget)

        # Страница 1: граф (сплиттер: palette | graph_view)
        self._graph_container = QSplitter(Qt.Orientation.Horizontal)
        self._catalog_palette = CatalogPalette()
        self._graph_scene = GraphScene()
        self._graph_view = GraphView(self._graph_scene)
        self._graph_container.addWidget(self._catalog_palette)
        self._graph_container.addWidget(self._graph_view)
        # Palette фиксированной ширины, graph_view растягивается
        self._graph_container.setStretchFactor(0, 0)
        self._graph_container.setStretchFactor(1, 1)
        self._stack.addWidget(self._graph_container)

        main_layout.addWidget(self._stack)

        # Данные графа (устанавливаются через set_data)
        self._nodes: dict = {}
        self._catalog: dict = {}

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def graph_scene(self) -> GraphScene:
        """Сцена графового редактора."""
        return self._graph_scene

    @property
    def graph_view(self) -> GraphView:
        """Вид графового редактора."""
        return self._graph_view

    @property
    def catalog_palette(self) -> CatalogPalette:
        """Панель каталога операций."""
        return self._catalog_palette

    @property
    def current_mode(self) -> str:
        """Текущий режим: 'table' или 'graph'."""
        return self._current_mode

    def set_data(self, nodes: dict, catalog: dict) -> None:
        """Установить данные графа (nodes + каталог).

        Args:
            nodes: dict node_id → ProcessingNode.
            catalog: dict type_key → ProcessingOperationDef.
        """
        self._nodes = nodes
        self._catalog = catalog
        self._catalog_palette.load_catalog(catalog)
        # Если уже в графовом виде — перезагружаем граф с новыми данными
        if self._current_mode == "graph":
            self._graph_scene.load_graph(nodes, catalog)

    def switch_to(self, mode: str) -> None:
        """Переключить вид программно.

        Args:
            mode: 'table' или 'graph'.
        """
        if mode == "graph":
            self._switch_btn.setChecked(True)
        else:
            self._switch_btn.setChecked(False)

    # ------------------------------------------------------------------
    # Внутренние обработчики
    # ------------------------------------------------------------------

    def _on_switch(self, checked: bool) -> None:
        """Обработчик переключения кнопки."""
        if checked:
            # Переключение на графовый вид
            self._current_mode = "graph"
            self._switch_btn.setText("Таблица")
            self._switch_btn.setToolTip("Переключить на табличный вид")
            # В графовом виде предупреждение не нужно
            self._warning_label.hide()
            # Загружаем граф с актуальными данными
            self._graph_scene.load_graph(self._nodes, self._catalog)
            self._stack.setCurrentIndex(1)
        else:
            # Переключение на табличный вид
            self._current_mode = "table"
            self._switch_btn.setText("Граф")
            self._switch_btn.setToolTip("Переключить на графовый вид")
            # Проверяем линейность и показываем предупреждение при необходимости
            warning = get_linearity_warning(self._nodes)
            if warning:
                self._warning_label.setText(warning)
                self._warning_label.show()
            else:
                self._warning_label.hide()
            self._stack.setCurrentIndex(0)

        self.view_changed.emit(self._current_mode)
