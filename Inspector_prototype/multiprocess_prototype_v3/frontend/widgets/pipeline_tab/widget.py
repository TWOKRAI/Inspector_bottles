"""PipelineTabWidget --- единая вкладка Pipeline: Library + canvas/table + Inspector.

Task 9.13 --- замена GraphEditorTabWidget. Собирает:
- LibraryPalette (левая панель, drag-source для операций каталога)
- PipelineViewSwitch (центр, graph canvas + table с переключателем)
- InspectorPanel (правая панель, свойства выбранной ноды)

NodeGraph + NodeGraphQtAdapter создаются здесь и передаются дочерним виджетам.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from PySide6 import QtWidgets

from frontend.actions.bus import ActionBus
from frontend.widgets.pipeline_tab.adapter import (
    INSPECTOR_NODE_TYPE,
    NodeGraphQtAdapter,
)
from frontend.widgets.pipeline_tab.inspector_panel import InspectorPanel
from frontend.widgets.pipeline_tab.library_palette import (
    LibraryPalette,
    install_palette_drop_target,
)
from frontend.widgets.pipeline_tab.model import GraphEditorModel
from frontend.widgets.pipeline_tab.table_view import PipelineTableView
from frontend.widgets.pipeline_tab.view_switch import PipelineViewSwitch

logger = logging.getLogger(__name__)


class PipelineTabWidget(QtWidgets.QWidget):
    """Единая вкладка Pipeline: Library + canvas/table + Inspector."""

    def __init__(
        self,
        *,
        action_bus: ActionBus,
        catalog: dict[str, Any],
        region_id: str = "default",
        known_processes_provider: Callable[[], list[str]] | None = None,
        known_displays_provider: Callable[[], list[str]] | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._catalog = catalog
        self._kpp = known_processes_provider or (lambda: [])
        self._kdp = known_displays_provider or (lambda: [])

        # 1. Модель данных графа
        self._model = GraphEditorModel()
        self._model.load({}, catalog)

        # 2. NodeGraph + регистрация InspectorBaseNode
        from NodeGraphQt import NodeGraph

        from frontend.widgets.pipeline_tab.inspector_node import InspectorBaseNode

        self._graph = NodeGraph()
        self._graph.register_node(InspectorBaseNode)

        # 3. Адаптер (мост между NodeGraphQt и бизнес-логикой)
        self._adapter = NodeGraphQtAdapter(
            graph=self._graph,
            model=self._model,
            action_bus=action_bus,
            catalog=catalog,
            region_id=region_id,
            parent=self,
        )

        # 4. Палитра операций (левая панель)
        self._palette = LibraryPalette()
        self._palette.load_catalog(catalog)
        self._palette.setFixedWidth(220)

        # Drop-target: перетаскивание из палитры на canvas
        self._drop_target = install_palette_drop_target(
            self._graph,
            self._adapter.add_node_from_catalog,
        )

        # 5. Табличный вид
        self._table = PipelineTableView(
            model=self._model,
            action_bus=action_bus,
            catalog=catalog,
            region_id=region_id,
            known_processes_provider=self._kpp,
        )

        # 6. Переключатель graph <-> table
        self._view_switch = PipelineViewSwitch(
            graph_widget=self._graph.widget,
            adapter=self._adapter,
            table_view=self._table,
        )

        # 7. Панель инспектора (правая)
        self._inspector = InspectorPanel(
            model=self._model,
            action_bus=action_bus,
            catalog=catalog,
            region_id=region_id,
            known_processes_provider=self._kpp,
            known_displays_provider=self._kdp,
        )
        self._inspector.setFixedWidth(320)

        # Связываем selection адаптера с инспектором
        self._adapter.node_selected.connect(self._inspector.show_node_by_id)
        self._adapter.selection_cleared.connect(self._inspector.clear)

        # 8. Layout: palette | view_switch (stretch) | inspector
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._palette, 0)
        layout.addWidget(self._view_switch, 1)
        layout.addWidget(self._inspector, 0)

    # ------------------------------------------------------------------
    # Публичные свойства и методы
    # ------------------------------------------------------------------

    @property
    def model(self) -> GraphEditorModel:
        """Модель данных графа (для интеграции с Recipe load)."""
        return self._model

    def set_pipeline(self, nodes: dict[str, Any]) -> None:
        """Заменить состояние графа: загрузить новые ноды.

        Args:
            nodes: dict node_id -> ProcessingNode (Pydantic-объект).
        """
        self._model.load(nodes, self._catalog)
        self._adapter.load_pipeline(nodes)
        self._table.refresh()
        self._inspector.clear()

    def current_pipeline(self) -> dict[str, Any]:
        """Read-only снимок текущего графа из model.nodes."""
        return deepcopy(self._model.nodes)


__all__ = ["PipelineTabWidget"]
