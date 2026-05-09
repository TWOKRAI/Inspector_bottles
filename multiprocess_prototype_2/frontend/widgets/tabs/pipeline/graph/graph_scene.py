"""GraphScene -- QGraphicsScene для DAG pipeline."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Signal
from PySide6.QtGui import QTransform
from PySide6.QtWidgets import QGraphicsScene, QMenu

from .constants import GRID_SPACING_X, GRID_SPACING_Y
from .node_item import NodeData, NodeItem
from .edge_item import EdgeData, EdgeItem


class GraphScene(QGraphicsScene):
    """Сцена DAG: узлы (NodeItem) + связи (EdgeItem).

    Работает с абстрактными NodeData/EdgeData.
    Не импортирует SystemBlueprint -- это делает presenter.
    """

    # Сигналы для context menu actions
    node_delete_requested = Signal(str)      # node_id
    node_inspect_requested = Signal(str)     # node_id
    edge_delete_requested = Signal(object)   # EdgeItem
    add_process_requested = Signal(float, float)  # scene x, y

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._nodes: dict[str, NodeItem] = {}
        self._edges: list[EdgeItem] = []

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load_from_data(
        self,
        nodes: list[NodeData],
        edges: list[EdgeData],
    ) -> None:
        """Построить граф из данных. Очищает предыдущее содержимое."""
        self.clear_all()

        # Авто-layout если координаты нулевые
        need_layout = all(n.x == 0 and n.y == 0 for n in nodes)

        for i, nd in enumerate(nodes):
            if need_layout:
                nd.x = (i % 4) * GRID_SPACING_X + 50
                nd.y = (i // 4) * GRID_SPACING_Y + 50
            self.add_node(nd)

        for ed in edges:
            self.add_edge(ed)

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def add_node(self, data: NodeData) -> NodeItem:
        """Добавить узел на сцену."""
        item = NodeItem(data)
        self.addItem(item)
        self._nodes[data.node_id] = item
        return item

    def remove_node(self, node_id: str) -> None:
        """Удалить узел и все связанные edge'ы."""
        item = self._nodes.pop(node_id, None)
        if item is None:
            return

        # Каскадное удаление связей
        edges_to_remove = [
            e for e in self._edges
            if e.source_id == node_id or e.target_id == node_id
        ]
        for edge in edges_to_remove:
            self._edges.remove(edge)
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
        return edge

    def on_node_moved(self, node_id: str) -> None:
        """Обновить все edge'ы, связанные с узлом (вызывается из NodeItem.itemChange)."""
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

    def remove_edge(self, edge: EdgeItem) -> None:
        """Удалить связь."""
        if edge in self._edges:
            self._edges.remove(edge)
            self.removeItem(edge)

    # ------------------------------------------------------------------ #
    #  Экспорт и утилиты                                                   #
    # ------------------------------------------------------------------ #

    def export_data(self) -> tuple[list[NodeData], list[EdgeData]]:
        """Экспортировать текущее состояние сцены."""
        nodes = []
        for nid, item in self._nodes.items():
            d = item.data
            # Обновить координаты из текущей позиции
            pos = item.pos()
            nodes.append(NodeData(
                node_id=d.node_id,
                title=d.title,
                subtitle=d.subtitle,
                category=d.category,
                x=pos.x(),
                y=pos.y(),
            ))

        edges = [e.edge_data for e in self._edges]
        return nodes, edges

    def clear_all(self) -> None:
        """Очистить все."""
        self.clear()
        self._nodes.clear()
        self._edges.clear()

    def node_count(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return len(self._edges)

    def get_node(self, node_id: str) -> NodeItem | None:
        return self._nodes.get(node_id)

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
        from .port_item import PortItem

        pos = event.scenePos()
        transform = self.views()[0].transform() if self.views() else QTransform()
        item = self.itemAt(pos, transform)

        # Пройти вверх по иерархии (PortItem -> NodeItem)
        target = item
        while target and not isinstance(target, (NodeItem, EdgeItem)):
            target = target.parentItem()

        if isinstance(target, NodeItem):
            self._show_node_menu(event, target)
        elif isinstance(target, EdgeItem):
            self._show_edge_menu(event, target)
        else:
            self._show_background_menu(event, pos)

    def _show_node_menu(self, event, node_item) -> None:
        """Контекстное меню для ноды."""
        menu = QMenu()
        inspect_action = menu.addAction("Inspect")
        menu.addSeparator()
        delete_action = menu.addAction("Delete")

        action = menu.exec(event.screenPos())
        if action == delete_action:
            self.node_delete_requested.emit(node_item.node_id)
        elif action == inspect_action:
            self.node_inspect_requested.emit(node_item.node_id)

    def _show_edge_menu(self, event, edge_item) -> None:
        """Контекстное меню для edge."""
        menu = QMenu()
        delete_action = menu.addAction("Delete")

        action = menu.exec(event.screenPos())
        if action == delete_action:
            self.edge_delete_requested.emit(edge_item)

    def _show_background_menu(self, event, pos) -> None:
        """Контекстное меню для пустого фона."""
        menu = QMenu()
        add_action = menu.addAction("Add Process...")

        action = menu.exec(event.screenPos())
        if action == add_action:
            self.add_process_requested.emit(pos.x(), pos.y())
