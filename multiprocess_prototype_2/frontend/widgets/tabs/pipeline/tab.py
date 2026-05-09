"""PipelineTab -- визуальный конструктор pipeline.

3-panel layout: PluginPalette + GraphView + NodeInspectorPanel.
D&D, selection, undo/redo, auto-layout, validate, shortcuts.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSplitter, QVBoxLayout, QWidget

from multiprocess_prototype_2.frontend.widgets.primitives import ActionToolbar

from .graph.graph_scene import GraphScene
from .graph.graph_view import GraphView
from .inspector import NodeInspectorPanel
from .palette import PluginPalette, PipelineDropTarget
from .presenter import PipelinePresenter

if TYPE_CHECKING:
    from PySide6.QtCore import QPointF
    from multiprocess_prototype_2.frontend.app_context import AppContext

logger = logging.getLogger(__name__)


class PipelineTab(QWidget):
    """Таб визуального конструктора pipeline.

    3-panel: палитра плагинов + canvas (граф) + инспектор параметров.
    Поддерживает: D&D из палитры, wire creation, undo/redo, auto-layout, validate.
    """

    def __init__(self, ctx: "AppContext", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._presenter = PipelinePresenter(ctx)

        self._init_ui()
        self._connect_signals()
        self._load_topology()
        self._load_palette()

    @classmethod
    def create(cls, ctx: "AppContext") -> "PipelineTab":
        return cls(ctx)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # Заголовок
        header = QLabel("Pipeline")
        header.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(header)

        # Тулбар: расширенный
        self._toolbar = ActionToolbar(actions=[
            ("undo", "Undo"),
            ("redo", "Redo"),
            ("delete", "Delete"),
            ("auto_layout", "Layout"),
            ("validate", "Validate"),
            ("fit", "Fit"),
            ("zoom_in", "Zoom +"),
            ("zoom_out", "Zoom -"),
        ])
        self._toolbar.action_triggered.connect(self._on_toolbar_action)
        layout.addWidget(self._toolbar)

        # QSplitter: 3 панели
        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая панель: палитра плагинов
        self._palette = PluginPalette()
        self._palette.setMinimumWidth(200)
        self._palette.setMaximumWidth(350)
        self._splitter.addWidget(self._palette)

        # Центральная панель: canvas
        self._scene = GraphScene()
        self._view = GraphView(self._scene)
        self._presenter.set_scene(self._scene)
        self._splitter.addWidget(self._view)

        # Правая панель: инспектор
        self._inspector = NodeInspectorPanel()
        self._inspector.setMinimumWidth(200)
        self._inspector.setMaximumWidth(400)
        self._splitter.addWidget(self._inspector)

        # Начальные размеры splitter
        self._splitter.setSizes([250, 600, 280])

        layout.addWidget(self._splitter, stretch=1)

        # Drop target для D&D из палитры
        self._drop_target = PipelineDropTarget(
            self._view, self._on_plugin_dropped
        )

    def _connect_signals(self) -> None:
        """Подключить сигналы."""
        # Wire creation
        self._view.wire_created.connect(self._on_wire_created)

        # Selection → inspector
        self._scene.selectionChanged.connect(self._on_selection_changed)

        # Inspector field changes
        self._inspector.field_changed.connect(self._on_inspector_field_changed)

    def _load_topology(self) -> None:
        """Загрузить topology из AppContext и отобразить."""
        nodes, edges = self._presenter.load_topology_from_config()
        self._scene.load_from_data(nodes, edges)

        if nodes:
            self._view.fit_to_view()

    def _load_palette(self) -> None:
        """Загрузить плагины в палитру."""
        registry = self._ctx.plugin_registry()
        if not registry:
            return

        plugins = []
        # registry может быть dict или объект с методом list/items
        if hasattr(registry, "items"):
            for name, entry in registry.items():
                plugins.append({
                    "name": name,
                    "category": getattr(entry, "category", "utility"),
                    "description": getattr(entry, "description", ""),
                })
        elif hasattr(registry, "list_plugins"):
            for entry in registry.list_plugins():
                plugins.append({
                    "name": getattr(entry, "name", ""),
                    "category": getattr(entry, "category", "utility"),
                    "description": getattr(entry, "description", ""),
                })

        if plugins:
            self._palette.load_plugins(plugins)

    # ------------------------------------------------------------------ #
    #  Обработчики                                                         #
    # ------------------------------------------------------------------ #

    def _on_toolbar_action(self, action_id: str) -> None:
        if action_id == "zoom_in":
            self._view.zoom_in()
        elif action_id == "zoom_out":
            self._view.zoom_out()
        elif action_id == "fit":
            self._view.fit_to_view()
        elif action_id == "validate":
            errors = self._presenter.validate()
            if errors:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Валидация", "\n".join(errors))
            else:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(self, "Валидация", "Topology валидна")
        elif action_id == "auto_layout":
            self._presenter.auto_layout_scene()
        elif action_id == "delete":
            selected = [
                item.node_id for item in self._scene.selectedItems()
                if hasattr(item, "node_id")
            ]
            if selected:
                self._presenter.remove_selected(selected)
                self._inspector.clear()
        elif action_id == "undo":
            bus = self._ctx.action_bus()
            if bus:
                bus.undo()
        elif action_id == "redo":
            bus = self._ctx.action_bus()
            if bus:
                bus.redo()

    def _on_plugin_dropped(self, plugin_name: str, scene_pos: "QPointF") -> None:
        """D&D из палитры → создать процесс на canvas."""
        self._presenter.add_process_from_plugin(
            plugin_name, scene_pos.x(), scene_pos.y()
        )

    def _on_wire_created(self, source_endpoint: str, target_endpoint: str) -> None:
        """Wire creation через GraphView."""
        self._presenter.add_wire(source_endpoint, target_endpoint)

    def _on_selection_changed(self) -> None:
        """Обработчик изменения выбора в scene."""
        selected = self._scene.selectedItems()
        node_items = [item for item in selected if hasattr(item, "node_id")]

        if len(node_items) == 1:
            node = node_items[0]
            # Получить данные процесса из topology
            topo = self._presenter.model.to_topology_dict()
            process_data = None
            for proc in topo.get("processes", []):
                if isinstance(proc, dict) and proc.get("process_name") == node.node_id:
                    process_data = proc
                    break

            plugins = process_data.get("plugins", []) if process_data else []
            category = node.data.category if hasattr(node, "data") else "utility"
            self._inspector.show_node(node.node_id, category, plugins=plugins)
        else:
            self._inspector.clear()

    def _on_inspector_field_changed(self, process_name: str, field_name: str, value) -> None:
        """Поле изменено в инспекторе."""
        # TODO: через ActionBus в Phase 13+
        logger.debug("Inspector field changed: %s.%s = %s", process_name, field_name, value)

    # ------------------------------------------------------------------ #
    #  Keyboard shortcuts                                                  #
    # ------------------------------------------------------------------ #

    def keyPressEvent(self, event) -> None:
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key.Key_Delete:
            self._on_toolbar_action("delete")
        elif key == Qt.Key.Key_Z and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._on_toolbar_action("undo")
        elif key == Qt.Key.Key_Y and modifiers & Qt.KeyboardModifier.ControlModifier:
            self._on_toolbar_action("redo")
        elif key == Qt.Key.Key_F:
            self._on_toolbar_action("fit")
        elif key == Qt.Key.Key_L:
            self._on_toolbar_action("auto_layout")
        else:
            super().keyPressEvent(event)
