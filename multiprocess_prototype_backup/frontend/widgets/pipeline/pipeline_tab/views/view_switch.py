"""PipelineViewSwitch — переключатель между графовым и табличным видами pipeline.

Хранит синхронизированное выделение ноды при переключении view.
При переключении graph→table — выделение передаётся в PipelineTableView.
При переключении table→graph — выделение передаётся в adapter (NodeGraphQtAdapter).

По умолчанию открывается в режиме «таблица» (page 1).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtWidgets

if TYPE_CHECKING:
    from frontend.widgets.pipeline.pipeline_tab.canvas.adapter import NodeGraphQtAdapter
    from frontend.widgets.pipeline.pipeline_tab.views.table_view import PipelineTableView

logger = logging.getLogger(__name__)

# Режимы view
MODE_GRAPH = "graph"
MODE_TABLE = "table"


class PipelineViewSwitch(QtWidgets.QWidget):
    """Переключатель graph ↔ table с синхронизацией выделения.

    Signals:
        view_changed(str): "graph" | "table" при смене режима.
        selection_changed(str): node_id или "" — единый канал для обоих views.
    """

    view_changed = QtCore.Signal(str)
    selection_changed = QtCore.Signal(str)

    def __init__(
        self,
        *,
        graph_widget: QtWidgets.QWidget,
        adapter: "NodeGraphQtAdapter",
        table_view: "PipelineTableView",
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        """Инициализация переключателя.

        Args:
            graph_widget: NodeGraph.widget() — виджет NodeGraphQt.
            adapter: NodeGraphQtAdapter — источник node_selected / selection_cleared.
            table_view: PipelineTableView — табличный вид.
            parent: Qt-родитель.
        """
        super().__init__(parent)

        self._graph_widget = graph_widget
        self._adapter = adapter
        self._table_view = table_view

        # Текущий выбранный node_id (синхронизируется между views)
        self._selected_node_id: str | None = None

        # Текущий режим
        self._current_mode: str = MODE_TABLE

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Создать layout: toolbar + QStackedWidget."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar с кнопкой переключения
        toolbar = QtWidgets.QWidget(self)
        toolbar_layout = QtWidgets.QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 4, 4, 4)

        self._toggle_btn = QtWidgets.QToolButton(self)
        self._toggle_btn.setText("Граф")
        self._toggle_btn.setToolTip("Переключить между графовым и табличным видом")
        self._toggle_btn.setCheckable(False)
        self._toggle_btn.clicked.connect(self._on_toggle_clicked)

        toolbar_layout.addWidget(self._toggle_btn)
        toolbar_layout.addStretch()

        # QStackedWidget: page 0 = graph, page 1 = table
        self._stack = QtWidgets.QStackedWidget(self)
        self._stack.addWidget(self._graph_widget)   # page 0 = graph
        self._stack.addWidget(self._table_view)     # page 1 = table

        layout.addWidget(toolbar)
        layout.addWidget(self._stack)

        # По умолчанию — table view (page 1)
        self._stack.setCurrentIndex(1)
        self._toggle_btn.setText("Граф")

    def _connect_signals(self) -> None:
        """Подключить сигналы от adapter и table_view."""
        # Сигналы adapter (NodeGraphQtAdapter — QObject с сигналами)
        self._adapter.node_selected.connect(self._on_graph_selected)
        self._adapter.selection_cleared.connect(self._on_graph_cleared)

        # Сигнал table_view
        self._table_view.selection_changed.connect(self._on_table_selected)

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    @property
    def current_mode(self) -> str:
        """Текущий режим: 'graph' | 'table'."""
        return self._current_mode

    def switch_to(self, mode: str) -> None:
        """Программно переключить режим.

        При переключении передаёт текущее выделение в целевой view.

        Args:
            mode: 'graph' | 'table'.
        """
        if mode == self._current_mode:
            return

        if mode == MODE_GRAPH:
            self._stack.setCurrentIndex(0)
            self._current_mode = MODE_GRAPH
            self._toggle_btn.setText("Таблица")

            # Передать выделение в graph
            if self._selected_node_id is not None:
                self._try_select_in_graph(self._selected_node_id)

        elif mode == MODE_TABLE:
            self._stack.setCurrentIndex(1)
            self._current_mode = MODE_TABLE
            self._toggle_btn.setText("Граф")

            # Передать выделение в table
            self._table_view.select_node(self._selected_node_id)

        else:
            logger.warning("PipelineViewSwitch.switch_to: неизвестный режим %r", mode)
            return

        self.view_changed.emit(mode)

    # ------------------------------------------------------------------
    # Обработчики переключения
    # ------------------------------------------------------------------

    def _on_toggle_clicked(self) -> None:
        """Обработать клик по кнопке переключения."""
        if self._current_mode == MODE_TABLE:
            self.switch_to(MODE_GRAPH)
        else:
            self.switch_to(MODE_TABLE)

    # ------------------------------------------------------------------
    # Обработчики сигналов от views
    # ------------------------------------------------------------------

    def _on_graph_selected(self, node_id: str) -> None:
        """Adapter сообщает о выделении ноды в graph view."""
        self._selected_node_id = node_id
        self.selection_changed.emit(node_id)

    def _on_graph_cleared(self) -> None:
        """Adapter сообщает о сбросе выделения в graph view."""
        self._selected_node_id = None
        self.selection_changed.emit("")

    def _on_table_selected(self, node_id: str) -> None:
        """Table view сообщает об изменении выделения."""
        if node_id:
            self._selected_node_id = node_id
        else:
            self._selected_node_id = None
        self.selection_changed.emit(node_id)

    # ------------------------------------------------------------------
    # Вспомогательный метод: выделить в graph view
    # ------------------------------------------------------------------

    def _try_select_in_graph(self, node_id: str) -> None:
        """Попытаться выделить ноду в NodeGraphQt через adapter.node_map.

        Не падает если нода не найдена — просто логирует.
        """
        try:
            node_map = getattr(self._adapter, "node_map", None)
            if node_map is None:
                # Fallback: ищем через _node_map (internal)
                node_map = getattr(self._adapter, "_node_map", None)
            if node_map and node_id in node_map:
                qt_node = node_map[node_id]
                qt_node.set_selected(True)
        except Exception as exc:
            logger.debug(
                "Не удалось выделить ноду %s в graph: %s",
                node_id,
                exc,
            )


__all__ = ["PipelineViewSwitch", "MODE_GRAPH", "MODE_TABLE"]
