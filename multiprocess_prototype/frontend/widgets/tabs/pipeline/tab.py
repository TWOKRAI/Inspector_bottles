# -*- coding: utf-8 -*-
"""PipelineTab — визуальный конструктор pipeline на едином columnar-шаблоне.

Task E.1: мигрирован на AppServices DI. Принимает services: AppServices как
основной параметр. create() принимает AppContext для TabFactory bridge (Phase F удалит).

3 колонки + мастер-скролл через ``DiffScrollTabLayout``:

- **action-колонка (1-я)**: все кнопки управления (Delete / Layout / Validate /
  Fit / Zoom+ / Zoom-); Undo/Redo — в статичной зоне снизу через
  ``enable_undo_redo``;
- **nav-колонка (2-я)**: ``PluginPalette`` — дерево плагинов по категориям +
  поиск + D&D на canvas;
- **content-колонка (3-я)**: вертикальный QSplitter с canvas (``GraphView``)
  сверху и ``NodeInspectorPanel`` (параметры выбранной ноды) снизу.

Внутренний скролл canvas НЕ передаётся в master-scrollbar — wheel на канве
выполняет zoom (нативное поведение ``GraphView``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from .graph.graph_scene import GraphScene
from .graph.graph_view import GraphView
from .inspector import NodeInspectorPanel
from .palette import PipelineDropTarget, PluginPalette
from .presenter import PipelinePresenter

if TYPE_CHECKING:
    from PySide6.QtCore import QPointF

    from multiprocess_prototype.frontend.app_context import AppContext

logger = logging.getLogger(__name__)


# Размеры колонок:
# - action_width: 180 — нужно место под 6 кнопок управления (Delete..Zoom);
# - nav_width:   345 — как в Plugins (русские имена категорий + tooltip).
_ACTION_WIDTH = 180
_NAV_WIDTH = 345


class PipelineTab(QWidget):
    """Таб визуального конструктора pipeline на ``DiffScrollTabLayout``.

    3 колонки (actions / palette / canvas+inspector) + мастер-скролл +
    QGroupBox-заголовок. Тулбар разнесён по action-колонке; Undo/Redo —
    в статичной зоне. Палитра плагинов — во 2-й колонке (дерево + поиск).
    Canvas + Inspector — в 3-й колонке через вертикальный сплиттер.
    """

    _MUTATING_ACTIONS = frozenset({"delete", "auto_layout", "undo", "redo", "save_recipe", "launch_recipe"})

    def __init__(self, services: AppServices, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self._presenter = PipelinePresenter(services)

        self._tab_layout = DiffScrollTabLayout(
            title="Pipeline",
            action_width=_ACTION_WIDTH,
            nav_width=_NAV_WIDTH,
        )

        # --- Action column: 6 кнопок (undo/redo — в статичной зоне) ---
        self._tab_layout.set_action_widget(self._build_action_widget())

        # --- Nav column: PluginPalette (дерево + поиск + D&D) ---
        self._palette = PluginPalette()
        self._tab_layout.set_nav_widget(self._palette)

        # --- Content column: canvas + inspector через QSplitter ---
        self._scene = GraphScene()
        self._view = GraphView(self._scene)
        self._inspector = NodeInspectorPanel()
        self._content_splitter = QSplitter(Qt.Orientation.Vertical)
        self._content_splitter.addWidget(self._view)
        self._content_splitter.addWidget(self._inspector)
        self._content_splitter.setStretchFactor(0, 3)  # canvas — 3/4
        self._content_splitter.setStretchFactor(1, 1)  # inspector — 1/4
        self._tab_layout.set_content_widget(self._content_splitter)

        # ВАЖНО: на canvas viewport DiffScrollTabLayout автоматически
        # устанавливает event filter и перехватывает wheel в master-scrollbar.
        # Это ломает zoom в GraphView. Снимаем filter — wheel на канве уйдёт
        # в её собственный wheelEvent (zoom).
        self._view.viewport().removeEventFilter(self._tab_layout)

        # Undo/Redo в статичной зоне (legacy ActionBus bridge).
        # TODO Phase F: полностью заменить ActionBus на domain commands
        _bus_accessor = getattr(services.commands, "action_bus", None)
        self._action_bus = _bus_accessor() if callable(_bus_accessor) else None
        self._tab_layout.enable_undo_redo(self._action_bus)

        # Передать scene и inspector в presenter.
        self._presenter.set_scene(self._scene)
        self._presenter.set_inspector(self._inspector)

        # Создать контроллер телеметрии edges (Task 7b.3)
        from .telemetry import WireMetricsController

        self._wire_metrics_controller = WireMetricsController(
            self._scene,
            self._presenter.wire_metrics_model,
            parent=self,
        )
        self._wire_metrics_controller.start()

        # Drop target для D&D из палитры на canvas.
        self._drop_target = PipelineDropTarget(self._view, self._on_plugin_dropped)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        main_layout.addWidget(self._tab_layout)

        self._connect_signals()
        self._load_topology()
        self._load_palette()

    @classmethod
    def create(cls, ctx: "AppContext") -> "PipelineTab":
        """Адаптер для TabFactory — принимает AppContext, извлекает AppServices.

        Phase F заменит AppContext на AppServices напрямую в register_all_tabs().
        """
        assert ctx.app_services is not None, (
            "AppServices не инициализирован в ctx. Убедитесь что Task D.1 factory вызван в run_gui()."
        )
        return cls(ctx.app_services)

    # ------------------------------------------------------------------ #
    #  Build helpers                                                       #
    # ------------------------------------------------------------------ #

    def _build_action_widget(self) -> QWidget:
        """6 кнопок управления в action-колонке."""
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        self._action_buttons: dict[str, QPushButton] = {}
        for action_id, label in [
            ("delete", "Удалить"),
            ("auto_layout", "Раскладка"),
            ("validate", "Валидация"),
            ("save_recipe", "Сохранить"),
            ("launch_recipe", "Запустить"),
            ("fit", "По размеру"),
            ("zoom_in", "Zoom +"),
            ("zoom_out", "Zoom −"),
        ]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, aid=action_id: self._on_toolbar_action(aid))
            action_layout.addWidget(btn)
            self._action_buttons[action_id] = btn

        action_layout.addStretch(1)

        # Permission gating: mutating actions (delete/auto_layout/save_recipe).
        # AuthFacade Protocol покрывает has_permission(), но install_permission_aware_enable
        # нуждается в AuthState (state.access_context_changed signal). Bridge через adapter.
        # TODO Phase F: расширить AuthFacade Protocol для runtime permission gating
        # (access_context_changed signal — нужен для install_permission_aware_enable).
        auth_state = getattr(self._services.auth, "_state", None)
        for aid in ("delete", "auto_layout", "save_recipe", "launch_recipe"):
            install_permission_aware_enable(
                self._action_buttons[aid],
                "tabs.pipeline.edit",
                auth_state,
            )

        return action_widget

    # ------------------------------------------------------------------ #
    #  Signals / topology / palette                                        #
    # ------------------------------------------------------------------ #

    def _connect_signals(self) -> None:
        """Подключить сигналы виджетов."""
        self._view.wire_created.connect(self._on_wire_created)
        self._scene.selectionChanged.connect(self._on_selection_changed)
        self._inspector.field_changed.connect(self._on_inspector_field_changed)

    def _load_topology(self) -> None:
        """Загрузить topology из AppContext и отобразить."""
        nodes, edges = self._presenter.load_topology_from_config()
        self._scene.load_from_data(nodes, edges)
        if nodes:
            self._view.fit_to_view()

    def _load_palette(self) -> None:
        """Загрузить плагины в палитру через services.plugins (PluginCatalog)."""
        plugin_specs = self._services.plugins.list_plugins()
        if not plugin_specs:
            return

        plugins = []
        for spec in plugin_specs:
            plugins.append(
                {
                    "name": spec.name,
                    "category": spec.category,
                    "description": spec.description,
                }
            )

        if plugins:
            self._palette.load_plugins(plugins)

    # ------------------------------------------------------------------ #
    #  Permissions                                                         #
    # ------------------------------------------------------------------ #

    def _can_edit(self) -> bool:
        """Имеет ли текущий пользователь право на mutation в pipeline."""
        return self._services.auth.has_permission("tabs.pipeline.edit")

    # ------------------------------------------------------------------ #
    #  Action handlers                                                     #
    # ------------------------------------------------------------------ #

    def _on_toolbar_action(self, action_id: str) -> None:
        if action_id in self._MUTATING_ACTIONS and not self._can_edit():
            return
        if action_id == "zoom_in":
            self._view.zoom_in()
        elif action_id == "zoom_out":
            self._view.zoom_out()
        elif action_id == "fit":
            self._view.fit_to_view()
        elif action_id == "validate":
            errors = self._presenter.validate()
            from PySide6.QtWidgets import QMessageBox

            if errors:
                QMessageBox.warning(self, "Валидация", "\n".join(errors))
            else:
                QMessageBox.information(self, "Валидация", "Topology валидна")
        elif action_id == "save_recipe":
            self._presenter.save_to_active_recipe(parent=self)
        elif action_id == "launch_recipe":
            self._presenter.launch_active_recipe(parent=self)
        elif action_id == "auto_layout":
            self._presenter.auto_layout_scene()
        elif action_id == "delete":
            selected = [item.node_id for item in self._scene.selectedItems() if hasattr(item, "node_id")]
            if selected:
                self._presenter.remove_selected(selected)
                self._inspector.clear()
        elif action_id == "undo":
            # TODO Phase F: domain command для undo
            if self._action_bus:
                self._action_bus.undo()
        elif action_id == "redo":
            # TODO Phase F: domain command для redo
            if self._action_bus:
                self._action_bus.redo()

    def _on_plugin_dropped(self, plugin_name: str, scene_pos: "QPointF") -> None:
        """D&D из палитры → создать процесс на canvas."""
        if not self._can_edit():
            return
        self._presenter.add_process_from_plugin(plugin_name, scene_pos.x(), scene_pos.y())

    def _on_wire_created(self, source_endpoint: str, target_endpoint: str) -> None:
        """Wire creation через GraphView.

        Передаёт self как parent для QMessageBox при несовместимых портах.
        """
        if not self._can_edit():
            return
        self._presenter.add_wire(source_endpoint, target_endpoint, parent=self)

    def _on_selection_changed(self) -> None:
        """Обработчик изменения выбора в scene.

        Определяет тип узла (plugin vs display) и вызывает соответствующий
        метод inspector'а: show_plugin_node или show_display_node.
        """
        from .graph.display_node_item import DisplayNodeItem

        selected = self._scene.selectedItems()
        node_items = [item for item in selected if hasattr(item, "node_id")]

        if len(node_items) == 1:
            node = node_items[0]
            topo = self._presenter.model.to_topology_dict()

            if isinstance(node, DisplayNodeItem):
                # Display-узел: найти запись в topology.displays
                display_id = ""
                display_name = ""
                for disp in topo.get("displays", []):
                    if isinstance(disp, dict) and disp.get("node_id") == node.node_id:
                        display_id = disp.get("display_id", "")
                        display_name = disp.get("display_name", "")
                        break

                # Если не найден в topology — взять из node.data
                if not display_id and hasattr(node, "data"):
                    display_id = getattr(node.data, "display_id", "")
                    display_name = getattr(node.data, "display_name", "")

                self._inspector.show_display_node(node.node_id, display_id, display_name)
            else:
                # Plugin-узел (process node)
                process_data = None
                for proc in topo.get("processes", []):
                    if isinstance(proc, dict) and proc.get("process_name") == node.node_id:
                        process_data = proc
                        break

                plugins = process_data.get("plugins", []) if process_data else []
                category = node.data.category if hasattr(node, "data") else "utility"
                target_process = process_data.get("target_process", "") if process_data else ""
                self._inspector.show_plugin_node(
                    node.node_id,
                    category,
                    target_process=target_process,
                    plugins=plugins,
                )
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
