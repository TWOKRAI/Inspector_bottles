"""GraphScene -- QGraphicsScene для DAG pipeline."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Signal
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsScene, QMenu

from .constants import GRID_SPACING_X, GRID_SPACING_Y
from .display_node_item import DisplayNodeData, DisplayNodeItem
from .node_item import NodeData, NodeItem
from .edge_item import EdgeData, EdgeItem
from .port_schema import PortSchema
from .process_container_item import ProcessContainerData, ProcessContainerItem


class GraphScene(QGraphicsScene):
    """Сцена DAG: узлы (NodeItem) + связи (EdgeItem).

    Работает с абстрактными NodeData/EdgeData.
    Не импортирует SystemBlueprint -- это делает presenter.
    """

    # Сигналы для context menu actions
    node_delete_requested = Signal(str)  # node_id
    node_inspect_requested = Signal(str)  # node_id
    node_lock_toggle_requested = Signal(str)  # node_id — зафиксировать/освободить
    edge_delete_requested = Signal(object)  # EdgeItem
    add_process_requested = Signal(float, float)  # scene x, y
    # Task 1.1: запрос на размещение пустого (непривязанного) display-бокса.
    # Несёт display_id выбранного канала + scene-координаты точки клика.
    add_display_requested = Signal(str, float, float)  # display_id, scene x, y

    # Сигналы жизненного цикла edges (Task 7b.3 — телеметрия)
    edge_added = Signal(object)  # EdgeItem — новый edge добавлен
    edge_removed = Signal(object)  # EdgeItem — edge удалён (до removeItem)

    # free-layout: нода свободно перемещена (node_id, scene x, y). Drag меняет ТОЛЬКО
    # позицию — членство в процессе НЕ трогается (смена процесса/воркера — через combo
    # инспектора). См. plans/2026-06-08_pipeline-free-layout.md (Task 1).
    node_position_changed = Signal(str, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Plugin-ноды (NodeItem) и display-боксы (DisplayNodeItem) живут в одном
        # реестре — чтобы add_edge находил target по id (binding-ребро source→box).
        self._nodes: dict[str, NodeItem | DisplayNodeItem] = {}
        self._edges: list[EdgeItem] = []
        # D.1: рамки-контейнеры процессов (key = process_name) + членство
        # плагин-нод по процессу (для fit, fallback get_node, drag/reorder).
        self._containers: dict[str, ProcessContainerItem] = {}
        self._members_by_process: dict[str, list[NodeItem]] = {}
        # Task 1.1: доступные display-каналы для подменю «Add Display →».
        # Пары (display_id, display_name). Заполняется из tab через
        # set_display_channels — scene НЕ имеет доступа к services.displays
        # (граница соблюдена: список каналов всегда приходит из tab).
        self._display_channels: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load_from_data(
        self,
        nodes: list[NodeData],
        edges: list[EdgeData],
        port_schemas_map: dict[str, list[PortSchema]] | None = None,
        display_nodes: list[DisplayNodeData] | None = None,
    ) -> None:
        """Построить граф из данных. Очищает предыдущее содержимое.

        port_schemas_map (node_id → схемы портов) — опционально; если задан,
        ноды строятся со Schema-Driven Ports (G.4.2: порты нужны для wire-тяжения
        после reload из TopologyReplaced). None → backward compat (1 input + 1 output).

        display_nodes (G.4.2b) — display-боксы (по одному на display_id-канал).
        Добавляются ДО рёбер, чтобы binding-ребро source→box нашло target в _nodes.
        """
        self.clear_all()

        # Авто-layout если координаты нулевые (только plugin-ноды)
        need_layout = all(n.x == 0 and n.y == 0 for n in nodes)

        for i, nd in enumerate(nodes):
            if need_layout:
                nd.x = (i % 4) * GRID_SPACING_X + 50
                nd.y = (i // 4) * GRID_SPACING_Y + 50
            ps = port_schemas_map.get(nd.node_id) if port_schemas_map else None
            self.add_node(nd, port_schemas=ps)

        # D.1: построить рамки-контейнеры по группам плагин-нод (process_name).
        # Ноды без process_name (raw/legacy) не группируются.
        self._rebuild_containers()

        # Display-боксы добавляем до рёбер (add_edge ищет target в _nodes)
        for dn in display_nodes or []:
            self.add_display_node(dn)

        for ed in edges:
            self.add_edge(ed)

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def add_node(
        self,
        data: NodeData,
        port_schemas: list[PortSchema] | None = None,
    ) -> NodeItem:
        """Добавить узел на сцену.

        Args:
            data: данные узла
            port_schemas: схемы портов плагина (Schema-Driven Ports).
                          Если None — backward compat: 1 input + 1 output.
        """
        item = NodeItem(data, port_schemas=port_schemas)
        self.addItem(item)
        self._nodes[data.node_id] = item
        # D.1: членство плагин-ноды в процессе (для контейнера/fit/drag).
        if data.process_name:
            self._members_by_process.setdefault(data.process_name, []).append(item)
        return item

    def add_display_node(self, data: DisplayNodeData) -> DisplayNodeItem:
        """Добавить display-бокс (SHM-канал) на сцену (G.4.2b).

        Кладёт в общий реестр _nodes по node_id (= display_id канала), чтобы
        binding-ребро source→box находило target через add_edge.
        """
        item = DisplayNodeItem(data)
        self.addItem(item)
        self._nodes[data.node_id] = item
        return item

    # ------------------------------------------------------------------ #
    #  Контейнеры процессов (D.1)                                          #
    # ------------------------------------------------------------------ #

    def _rebuild_containers(self) -> None:
        """Пересоздать рамки-контейнеры по текущим группам плагин-нод.

        Один контейнер на process_name (только непустые группы). Вызывается
        после массового add_node в load_from_data.
        """
        for cont in self._containers.values():
            self.removeItem(cont)
        self._containers.clear()
        for process_name, members in self._members_by_process.items():
            if not process_name or not members:
                continue
            cont = ProcessContainerItem(ProcessContainerData(process_name=process_name))
            self.addItem(cont)
            cont.fit_to_members(members)
            self._containers[process_name] = cont

    def _refit_container(self, process_name: str) -> None:
        """Пересчитать геометрию контейнера процесса по его членам."""
        cont = self._containers.get(process_name)
        if cont is not None:
            cont.fit_to_members(self._members_by_process.get(process_name, []))

    def get_container(self, process_name: str) -> ProcessContainerItem | None:
        """Вернуть рамку-контейнер процесса (или None)."""
        return self._containers.get(process_name)

    def members_of(self, process_name: str) -> list[NodeItem]:
        """Плагин-ноды процесса в порядке добавления (для drag/reorder)."""
        return list(self._members_by_process.get(process_name, []))

    def remove_node(self, node_id: str) -> None:
        """Удалить узел и все связанные edge'ы."""
        item = self._nodes.pop(node_id, None)
        if item is None:
            return

        # Снять членство в процессе + обновить/убрать контейнер.
        process_name = getattr(item, "process_name", "")
        if process_name and process_name in self._members_by_process:
            members = self._members_by_process[process_name]
            if item in members:
                members.remove(item)
            if members:
                self._refit_container(process_name)
            else:
                self._members_by_process.pop(process_name, None)
                cont = self._containers.pop(process_name, None)
                if cont is not None:
                    self.removeItem(cont)

        # Каскадное удаление связей
        edges_to_remove = [e for e in self._edges if e.source_id == node_id or e.target_id == node_id]
        for edge in edges_to_remove:
            self._edges.remove(edge)
            # Уведомить до removeItem — после удаления из сцены edge недоступен (Task 7b.3).
            # implicit-стрелки телеметрию не шлют (edge_added не было) → не эмитим.
            if not edge.implicit:
                self.edge_removed.emit(edge)
            self.removeItem(edge)

        self.removeItem(item)

    def add_edge(self, data: EdgeData) -> EdgeItem | None:
        """Добавить связь. Обновляет path по позициям узлов."""
        source_node = self._nodes.get(data.source_id)
        target_node = self._nodes.get(data.target_id)

        if source_node is None or target_node is None:
            return None

        edge = EdgeItem(data)
        edge.update_path(
            source_node.output_port_pos(),
            target_node.input_port_pos(),
        )
        self.addItem(edge)
        self._edges.append(edge)
        # Уведомить подписчиков о добавлении нового edge (Task 7b.3).
        # implicit-стрелки цепочки — визуальные, не шлют edge-телеметрию.
        if not data.implicit:
            self.edge_added.emit(edge)
        return edge

    def on_node_moved(self, node_id: str) -> None:
        """Обновить edge'ы и контейнер процесса (вызывается из NodeItem.itemChange)."""
        node = self._nodes.get(node_id)
        if node is None:
            return
        for edge in self._edges:
            if edge.source_id == node_id or edge.target_id == node_id:
                source = self._nodes.get(edge.source_id)
                target = self._nodes.get(edge.target_id)
                if source and target:
                    edge.update_path(
                        source.output_port_pos(),
                        target.input_port_pos(),
                    )
        # D.1: подвинули плагин-ноду — пересчитать рамку её процесса.
        process_name = getattr(node, "process_name", "")
        if process_name:
            self._refit_container(process_name)

    def on_node_drag_finished(self, node_id: str) -> None:
        """free-layout: нода отпущена после перетаскивания — фиксируем новую позицию.

        Drag = ТОЛЬКО перемещение: членство ноды в процессе НЕ меняется (никаких
        MovePlugin/snap-back и «объединения под процесс»). Эмитит node_position_changed
        с новой scene-позицией; presenter записывает её в gui_positions и дебаунс-
        сохраняет в рецепт. Смена процесса/воркера — только через combo инспектора.
        См. plans/2026-06-08_pipeline-free-layout.md (Task 1).
        """
        node = self._nodes.get(node_id)
        if node is None:
            return
        pos = node.pos()
        self.node_position_changed.emit(node_id, pos.x(), pos.y())

    def remove_edge(self, edge: EdgeItem) -> None:
        """Удалить связь."""
        if edge in self._edges:
            self._edges.remove(edge)
            # Уведомить до removeItem (Task 7b.3); implicit-стрелки телеметрию не шлют.
            if not edge.implicit:
                self.edge_removed.emit(edge)
            self.removeItem(edge)

    # ------------------------------------------------------------------ #
    #  Экспорт и утилиты                                                   #
    # ------------------------------------------------------------------ #

    def export_data(self) -> tuple[list[NodeData], list[EdgeData]]:
        """Экспортировать текущее состояние сцены."""
        nodes = []
        for nid, item in self._nodes.items():
            d = item.data
            # Display-боксы не экспортируются как process-NodeData (нет title/subtitle).
            # Их состояние живёт в topology["displays"] (binding), не в graph-NodeData.
            if not hasattr(d, "title"):
                continue
            # Обновить координаты из текущей позиции
            pos = item.pos()
            nodes.append(
                NodeData(
                    node_id=d.node_id,
                    title=d.title,
                    subtitle=d.subtitle,
                    category=d.category,
                    x=pos.x(),
                    y=pos.y(),
                    process_name=getattr(d, "process_name", ""),
                    plugin_index=getattr(d, "plugin_index", -1),
                    plugin_name=getattr(d, "plugin_name", ""),
                )
            )

        # implicit-стрелки цепочки — визуальные, не часть domain-топологии.
        edges = [e.edge_data for e in self._edges if not e.implicit]
        return nodes, edges

    def clear_all(self) -> None:
        """Очистить все узлы и связи.

        Эмиттит edge_removed для каждого wire ДО clear() — это даёт
        слушателям (например, WireMetricsController) шанс снять свои
        QGraphicsItem'ы до того, как Qt их уничтожит, и избежать
        ссылок на удалённые C++ объекты.
        """
        for edge in list(self._edges):
            # implicit-стрелки телеметрию не получали → не уведомляем о снятии.
            if not edge.implicit:
                self.edge_removed.emit(edge)
        self.clear()
        self._nodes.clear()
        self._edges.clear()
        self._containers.clear()
        self._members_by_process.clear()

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return len(self._edges)

    def get_node(self, node_id: str) -> NodeItem | DisplayNodeItem | None:
        """Найти узел по id.

        D.1: помимо прямого совпадения по node_id (плагин-нода `proc.plugin`,
        display-бокс `display_id`) поддержан удобный fallback по ИМЕНИ ПРОЦЕССА:
        если node_id — имя процесса с плагин-нодами, возвращается первая нода
        процесса. Это сохраняет совместимость с вызовами `get_node(process_name)`
        (reveal новой ноды, тесты) после перехода node=plugin.
        """
        item = self._nodes.get(node_id)
        if item is not None:
            return item
        members = self._members_by_process.get(node_id)
        if members:
            return members[0]
        return None

    def set_display_channels(self, channels: list[tuple[str, str]]) -> None:
        """Задать список display-каналов для подменю «Add Display →» (Task 1.1).

        channels — пары (display_id, display_name). Передаётся из tab, который
        читает services.displays.list_displays(). Пустой список → подменю disabled.
        """
        self._display_channels = list(channels)

    def get_all_node_positions(self) -> dict[str, tuple[float, float]]:
        """Вернуть позиции всех нод {node_id: (x, y)}."""
        return {nid: (item.pos().x(), item.pos().y()) for nid, item in self._nodes.items()}

    def set_node_locked(self, node_id: str, locked: bool) -> None:
        """Зафиксировать/освободить плагин-ноду по id (no-op для display-боксов)."""
        item = self._nodes.get(node_id)
        if item is not None and hasattr(item, "set_locked"):
            item.set_locked(locked)

    def port_at(self, scene_pos: tuple[float, float]):
        """Найти PortItem в точке scene_pos."""
        from .port_item import PortItem

        x, y = scene_pos
        items = self.items(QPointF(x, y))
        for item in items:
            if isinstance(item, PortItem):
                return item
        return None

    # ------------------------------------------------------------------ #
    #  Контекстные меню                                                    #
    # ------------------------------------------------------------------ #

    def contextMenuEvent(self, event) -> None:
        """Контекстное меню: зависит от того, на чём кликнули."""
        from .node_item import NodeItem
        from .edge_item import EdgeItem
        from .display_node_item import DisplayNodeItem

        pos = event.scenePos()
        transform = self.views()[0].transform() if self.views() else QTransform()
        item = self.itemAt(pos, transform)

        # Пройти вверх по иерархии (PortItem/TextItem -> NodeItem / DisplayNodeItem).
        # DisplayNodeItem наследует QGraphicsRectItem напрямую (не от NodeItem),
        # поэтому его нужно явно включить в условие остановки обхода.
        target = item
        while target and not isinstance(target, (NodeItem, DisplayNodeItem, EdgeItem)):
            target = target.parentItem()

        if isinstance(target, (NodeItem, DisplayNodeItem)):
            self._show_node_menu(event, target)
        elif isinstance(target, EdgeItem) and not target.implicit:
            # implicit-стрелка цепочки не удаляется пользователем → меню фона.
            self._show_edge_menu(event, target)
        else:
            self._show_background_menu(event, pos)

    def _show_node_menu(self, event, node_item) -> None:
        """Контекстное меню для ноды."""
        menu = QMenu()
        inspect_action = menu.addAction("Inspect")
        # Лок доступен только для плагин-нод (NodeItem с set_locked).
        lock_action = None
        if hasattr(node_item, "set_locked"):
            label = "Открепить" if getattr(node_item, "locked", False) else "Зафиксировать"
            lock_action = menu.addAction(label)
        menu.addSeparator()
        delete_action = menu.addAction("Delete")

        action = menu.exec(event.screenPos())
        if action == delete_action:
            self.node_delete_requested.emit(node_item.node_id)
        elif action == inspect_action:
            self.node_inspect_requested.emit(node_item.node_id)
        elif lock_action is not None and action == lock_action:
            self.node_lock_toggle_requested.emit(node_item.node_id)

    def _show_edge_menu(self, event, edge_item) -> None:
        """Контекстное меню для edge."""
        menu = QMenu()
        delete_action = menu.addAction("Delete")

        action = menu.exec(event.screenPos())
        if action == delete_action:
            self.edge_delete_requested.emit(edge_item)

    def _show_background_menu(self, event, pos) -> None:
        """Контекстное меню для пустого фона.

        Task 1.1: помимо «Add Process...» строит подменю «Add Display →» с одним
        пунктом на каждый display-канал из self._display_channels. Выбор display-
        пункта эмитит add_display_requested(display_id, x, y). Если каналов нет —
        подменю disabled.
        """
        menu = QMenu()
        add_action = menu.addAction("Add Process...")

        # Подменю выбора display-канала. display_id храним в action.setData(...),
        # а сами display-actions — в локальном множестве, чтобы после exec точно
        # отличить выбор display-пункта от «Add Process...» / отмены меню.
        display_menu = menu.addMenu("Add Display →")
        display_actions = set()
        if self._display_channels:
            for display_id, display_name in self._display_channels:
                act = display_menu.addAction(display_name or display_id)
                act.setData(display_id)
                display_actions.add(act)
        else:
            display_menu.setEnabled(False)

        action = menu.exec(event.screenPos())
        if action == add_action:
            self.add_process_requested.emit(pos.x(), pos.y())
        elif action in display_actions:
            self.add_display_requested.emit(action.data(), pos.x(), pos.y())
