"""GraphScene — QGraphicsScene с grid-фоном, управлением нодами и рёбрами."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from PyQt5.QtCore import QRectF, Qt, QTimeLine, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QGraphicsScene

from .catalog_palette import MIME_TYPE
from .constants import (
    AUTO_LAYOUT_X,
    AUTO_LAYOUT_Y_START,
    AUTO_LAYOUT_Y_STEP,
    GRID_COLOR,
    GRID_SIZE,
    SCENE_BG_COLOR,
)
from .edge_item import EdgeItem
from .node_item import NodeItem
from .port_item import PortItem
from .provisional_edge import ProvisionalEdge


class GraphScene(QGraphicsScene):
    """Сцена графового редактора: ноды, рёбра, сетка точками.

    Сигналы:
        node_moved(node_id, x, y): узел перемещён.
        node_selected(node_id): узел выделен.
        selection_changed_ids(list[str]): изменился набор выделенных узлов.
        node_added(dict): новый узел добавлен через drag-drop или дублирование.
        node_removed(str, dict): узел удалён (node_id, info).
        node_toggled(str, bool): узел включён/отключён.
        edge_created(src_id, out_port, tgt_id, in_port): связь создана.
        edge_removed(src_id, out_port, tgt_id, in_port): связь удалена.
    """

    # Сигналы — базовые
    node_moved = pyqtSignal(str, float, float)
    node_selected = pyqtSignal(str)
    selection_changed_ids = pyqtSignal(list)
    node_added = pyqtSignal(dict)  # {node_id, operation_ref, position}

    # Сигналы — интеракции (Task 8.4)
    node_removed = pyqtSignal(str, dict)
    node_toggled = pyqtSignal(str, bool)
    edge_created = pyqtSignal(str, str, str, str)
    edge_removed = pyqtSignal(str, str, str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # Хранилища
        self._node_items: dict[str, NodeItem] = {}
        self._edge_items: list[EdgeItem] = []

        # Каталог операций: type_key → ProcessingOperationDef
        # Заполняется через load_graph() или set_catalog()
        self._catalog: dict[str, Any] = {}

        # Состояние drag-connect (создание связей перетаскиванием)
        self._dragging_edge: ProvisionalEdge | None = None
        self._drag_source_port: PortItem | None = None
        self._highlighted_ports: list[PortItem] = []

        # Фон
        self.setBackgroundBrush(QBrush(SCENE_BG_COLOR))

        # Размер сцены по умолчанию
        self.setSceneRect(-2000, -2000, 4000, 4000)

        # Подписка на изменение выделения
        self.selectionChanged.connect(self._on_selection_changed)

    # ------------------------------------------------------------------
    # Загрузка графа из данных ProcessingNode
    # ------------------------------------------------------------------

    def load_graph(
        self,
        nodes: dict[str, ProcessingNode],  # noqa: F821
        catalog: dict[str, ProcessingOperationDef],  # noqa: F821
    ) -> None:
        """Загрузить граф: создать NodeItem и EdgeItem для каждого узла и связи.

        Args:
            nodes: словарь node_id → ProcessingNode.
            catalog: словарь type_key → ProcessingOperationDef.
        """
        # Очистка
        self.clear()
        self._node_items.clear()
        self._edge_items.clear()

        # Сохраняем каталог для drag-drop операций
        self._catalog = catalog

        if not nodes:
            # Пустой граф — ничего не создаём, placeholder нарисуется в drawBackground
            return

        # --- Auto-layout для нод без сохранённой позиции ---
        needs_layout = any(n.position is None for n in nodes.values())
        layout_positions: dict[str, tuple[float, float]] = {}
        if needs_layout:
            from .auto_layout import auto_layout

            layout_positions = auto_layout(nodes)

        # --- Создаём ноды ---
        auto_y = AUTO_LAYOUT_Y_START
        for node_id, node in nodes.items():
            op_def = catalog.get(node.operation_ref)
            if op_def is None:
                # Операция не найдена в каталоге — пропускаем
                continue

            # Позиция: сохранённая → auto-layout → fallback столбец
            if node.position is not None:
                pos_x, pos_y = node.position
            elif node_id in layout_positions:
                pos_x, pos_y = layout_positions[node_id]
            else:
                pos_x = AUTO_LAYOUT_X
                pos_y = auto_y
                auto_y += AUTO_LAYOUT_Y_STEP

            self.add_node(node_id, op_def, (pos_x, pos_y), enabled=node.enabled)

        # --- Создаём рёбра ---
        for node_id, node in nodes.items():
            for inp in node.inputs:
                source_id = inp.source
                if source_id in self._node_items and node_id in self._node_items:
                    self.add_edge(source_id, inp.output_port, node_id, inp.input_port)

    # ------------------------------------------------------------------
    # Управление нодами
    # ------------------------------------------------------------------

    def add_node(
        self,
        node_id: str,
        op_def: ProcessingOperationDef,  # noqa: F821
        position: tuple[float, float],
        enabled: bool = True,
    ) -> NodeItem:
        """Добавить узел на сцену.

        Args:
            node_id: UUID узла.
            op_def: определение операции из каталога.
            position: (x, y) на сцене.
            enabled: включён ли узел.

        Returns:
            Созданный NodeItem.
        """
        # Подготовка данных портов: (name, data_type, optional)
        input_ports_data = [(p.name, p.data_type, p.optional) for p in op_def.input_ports]
        output_ports_data = [(p.name, p.data_type, p.optional) for p in op_def.output_ports]

        node_item = NodeItem(
            node_id=node_id,
            operation_name=op_def.name,
            input_ports_data=input_ports_data,
            output_ports_data=output_ports_data,
            enabled=enabled,
        )
        node_item.setPos(position[0], position[1])
        self.addItem(node_item)
        self._node_items[node_id] = node_item

        return node_item

    def remove_node(self, node_id: str) -> None:
        """Удалить узел и все связанные рёбра."""
        node_item = self._node_items.pop(node_id, None)
        if node_item is None:
            return

        # Удаляем все рёбра, связанные с этой нодой
        edges_to_remove = [
            edge
            for edge in self._edge_items
            if (
                edge.source_port.parent_node_item is node_item
                or edge.target_port.parent_node_item is node_item
            )
        ]
        for edge in edges_to_remove:
            self.remove_edge(edge)

        self.removeItem(node_item)

    def get_node(self, node_id: str) -> NodeItem | None:
        """Получить NodeItem по node_id."""
        return self._node_items.get(node_id)

    # ------------------------------------------------------------------
    # Управление рёбрами
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source_node_id: str,
        output_port: str,
        target_node_id: str,
        input_port: str,
    ) -> EdgeItem | None:
        """Создать ребро между портами двух нод.

        Returns:
            Созданный EdgeItem или None если порты не найдены.
        """
        source_node = self._node_items.get(source_node_id)
        target_node = self._node_items.get(target_node_id)
        if source_node is None or target_node is None:
            return None

        source_port_item = source_node.get_port(output_port, is_input=False)
        target_port_item = target_node.get_port(input_port, is_input=True)
        if source_port_item is None or target_port_item is None:
            return None

        edge = EdgeItem(source_port_item, target_port_item)
        self.addItem(edge)
        self._edge_items.append(edge)
        return edge

    def remove_edge(self, edge_item: EdgeItem) -> None:
        """Удалить ребро из сцены."""
        if edge_item in self._edge_items:
            self._edge_items.remove(edge_item)
        edge_item.detach()
        self.removeItem(edge_item)

    # ------------------------------------------------------------------
    # Удаление с эмиссией сигналов (Task 8.4)
    # ------------------------------------------------------------------

    def delete_node_with_signal(self, node_id: str) -> None:
        """Удалить узел и emit node_removed."""
        node_item = self._node_items.get(node_id)
        if node_item is None:
            return

        # Собираем информацию до удаления
        info = {
            "node_id": node_id,
            "operation_name": node_item.operation_name,
            "position": (node_item.pos().x(), node_item.pos().y()),
        }

        # Удаляем связанные рёбра с сигналами
        edges_to_remove = [
            edge
            for edge in list(self._edge_items)
            if (
                edge.source_port.parent_node_item is node_item
                or edge.target_port.parent_node_item is node_item
            )
        ]
        for edge in edges_to_remove:
            self.remove_edge_with_signal(edge)

        # Удаляем саму ноду
        self._node_items.pop(node_id, None)
        self.removeItem(node_item)

        self.node_removed.emit(node_id, info)

    def remove_edge_with_signal(self, edge_item: EdgeItem) -> None:
        """Удалить ребро и emit edge_removed."""
        src_node = edge_item.source_port.parent_node_item
        tgt_node = edge_item.target_port.parent_node_item
        src_port = edge_item.source_port.port_name
        tgt_port = edge_item.target_port.port_name

        self.remove_edge(edge_item)
        self.edge_removed.emit(src_node.node_id, src_port, tgt_node.node_id, tgt_port)

    # ------------------------------------------------------------------
    # Дублирование ноды (Task 8.4)
    # ------------------------------------------------------------------

    def duplicate_node(self, node_item: NodeItem) -> None:
        """Создать копию узла со смещением (40, 40), без связей."""
        new_id = str(uuid4())
        old_pos = node_item.pos()
        new_pos = (old_pos.x() + 40, old_pos.y() + 40)

        # Собираем данные портов из оригинального узла
        input_ports_data = [
            (p.port_name, p.data_type, p.is_optional) for p in node_item.input_ports
        ]
        output_ports_data = [
            (p.port_name, p.data_type, p.is_optional) for p in node_item.output_ports
        ]

        new_node = NodeItem(
            node_id=new_id,
            operation_name=node_item.operation_name,
            input_ports_data=input_ports_data,
            output_ports_data=output_ports_data,
            enabled=node_item.opacity() > 0.5,
        )
        new_node.setPos(new_pos[0], new_pos[1])
        self.addItem(new_node)
        self._node_items[new_id] = new_node

        self.node_added.emit(
            {
                "node_id": new_id,
                "operation_name": node_item.operation_name,
                "position": new_pos,
                "source_node_id": node_item.node_id,
            }
        )

    # ------------------------------------------------------------------
    # Удаление выделенных элементов (Del)
    # ------------------------------------------------------------------

    def delete_selected(self) -> None:
        """Удалить все выделенные узлы и рёбра."""
        selected = self.selectedItems()
        if not selected:
            return

        # Сначала удаляем рёбра (они могут быть выделены отдельно)
        for item in list(selected):
            if isinstance(item, EdgeItem):
                self.remove_edge_with_signal(item)

        # Затем удаляем ноды (они удалят свои рёбра автоматически)
        for item in list(selected):
            if isinstance(item, NodeItem):
                self.delete_node_with_signal(item.node_id)

    # ------------------------------------------------------------------
    # Drag-connect: создание связей перетаскиванием (Task 8.4)
    # ------------------------------------------------------------------

    def start_edge_drag(self, source_port: PortItem) -> None:
        """Начать drag-создание связи от output-порта."""
        self._drag_source_port = source_port
        self._dragging_edge = ProvisionalEdge(source_port)
        self.addItem(self._dragging_edge)
        self._highlight_compatible_ports(source_port)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        """Обновление provisional edge при drag-connect."""
        if self._dragging_edge is not None:
            scene_pos = event.scenePos()
            self._dragging_edge.update_target(scene_pos)

            # Проверяем порт под курсором для визуальной обратной связи
            port_under = self._find_port_at(scene_pos)
            if port_under is not None and port_under.is_input:
                compatible = self._check_drag_compatible(port_under)
                self._dragging_edge.set_invalid(not compatible)
            else:
                self._dragging_edge.set_invalid(False)

            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        """Завершение drag-connect: создание связи или отмена."""
        if self._dragging_edge is not None:
            self._finish_edge_drag(event.scenePos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _finish_edge_drag(self, scene_pos) -> None:
        """Завершить drag: проверить порт-приёмник, создать связь или отменить."""
        target_port = self._find_port_at(scene_pos)

        if (
            target_port is not None
            and target_port.is_input
            and self._drag_source_port is not None
            and self._check_drag_compatible(target_port)
        ):
            source_port = self._drag_source_port
            source_node = source_port.parent_node_item
            target_node = target_port.parent_node_item

            # Запрет самосоединения
            if source_node is not target_node:
                # Если input уже занят — удаляем старую связь
                self._disconnect_existing_input(target_port)

                # Создаём связь
                edge = self.add_edge(
                    source_node.node_id,
                    source_port.port_name,
                    target_node.node_id,
                    target_port.port_name,
                )
                if edge is not None:
                    self.edge_created.emit(
                        source_node.node_id,
                        source_port.port_name,
                        target_node.node_id,
                        target_port.port_name,
                    )

        # Убираем provisional edge
        if self._dragging_edge is not None:
            self.removeItem(self._dragging_edge)
            self._dragging_edge = None

        self._drag_source_port = None
        self._clear_highlights()

    def _find_port_at(self, scene_pos) -> PortItem | None:
        """Найти PortItem под указанной позицией на сцене."""
        items = self.items(scene_pos)
        for item in items:
            if isinstance(item, PortItem):
                return item
        return None

    def _check_drag_compatible(self, target_port: PortItem) -> bool:
        """Проверить совместимость target_port с drag_source_port."""
        if self._drag_source_port is None:
            return False

        # Должен быть input-порт
        if not target_port.is_input:
            return False

        # Не на той же ноде (запрет самосоединения)
        if target_port.parent_node_item is self._drag_source_port.parent_node_item:
            return False

        # Совместимость типов данных
        from registers.processor.catalog.port_types import are_ports_compatible

        return are_ports_compatible(self._drag_source_port.data_type, target_port.data_type)

    def _disconnect_existing_input(self, target_port: PortItem) -> None:
        """Если input-порт уже имеет связь — удалить старую (input принимает 1 связь)."""
        for edge in list(self._edge_items):
            if edge.target_port is target_port:
                self.remove_edge_with_signal(edge)
                break

    # ------------------------------------------------------------------
    # Подсветка совместимых портов при drag-connect
    # ------------------------------------------------------------------

    def _highlight_compatible_ports(self, source_port: PortItem) -> None:
        """Подсветить все совместимые input-порты зелёным, несовместимые — полупрозрачными."""
        from registers.processor.catalog.port_types import are_ports_compatible

        self._highlighted_ports.clear()

        for node_item in self._node_items.values():
            # Пропускаем ту же ноду (самосоединение запрещено)
            if node_item is source_port.parent_node_item:
                continue

            for port in node_item.input_ports:
                compatible = are_ports_compatible(source_port.data_type, port.data_type)
                port.set_highlight_compatible(compatible)
                self._highlighted_ports.append(port)

    def _clear_highlights(self) -> None:
        """Вернуть все подсвеченные порты в нормальное состояние."""
        for port in self._highlighted_ports:
            port.clear_highlight()
        self._highlighted_ports.clear()

    # ------------------------------------------------------------------
    # Контекстное меню (Task 8.4)
    # ------------------------------------------------------------------

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """Показать контекстное меню в зависимости от элемента под курсором."""
        from PyQt5.QtGui import QTransform

        from .context_menu import show_edge_context_menu, show_node_context_menu

        # Получаем трансформацию вида для корректного определения элемента
        transform = self.views()[0].transform() if self.views() else QTransform()
        item = self.itemAt(event.scenePos(), transform)

        # PortItem — переходим к родительскому NodeItem
        if isinstance(item, PortItem):
            item = item.parent_node_item

        if isinstance(item, NodeItem):
            show_node_context_menu(self, item, event.screenPos())
        elif isinstance(item, EdgeItem):
            show_edge_context_menu(self, item, event.screenPos())
        else:
            # Пустое место — меню обрабатывается в GraphView.contextMenuEvent
            event.ignore()

    # ------------------------------------------------------------------
    # Сигналы выделения
    # ------------------------------------------------------------------

    def _on_selection_changed(self) -> None:
        """Обработчик изменения выделения: эмитит сигналы."""
        selected_ids = [item.node_id for item in self.selectedItems() if isinstance(item, NodeItem)]
        self.selection_changed_ids.emit(selected_ids)

        # Если выделен ровно один узел — эмитим node_selected
        if len(selected_ids) == 1:
            self.node_selected.emit(selected_ids[0])

    # ------------------------------------------------------------------
    # Auto-layout: автоматическое расположение узлов
    # ------------------------------------------------------------------

    def apply_auto_layout(self, nodes: dict[str, Any]) -> None:
        """Применить auto-layout ко всем нодам на сцене (с анимацией).

        Args:
            nodes: словарь node_id → ProcessingNode (для вычисления зависимостей).
        """
        from .auto_layout import auto_layout

        positions = auto_layout(nodes)
        for node_id, (x, y) in positions.items():
            node_item = self._node_items.get(node_id)
            if node_item is not None:
                self._animate_node_move(node_item, x, y)
                self.node_moved.emit(node_id, x, y)

    def _animate_node_move(self, node_item: NodeItem, x: float, y: float) -> None:
        """Плавное перемещение ноды к новой позиции (300ms).

        QGraphicsItem не поддерживает QPropertyAnimation напрямую,
        поэтому используем QTimeLine для пошагового перемещения.
        """
        timeline = QTimeLine(300)
        timeline.setFrameRange(0, 30)
        start_pos = node_item.pos()

        def _step(frame: int) -> None:
            t = frame / 30.0
            cx = start_pos.x() + (x - start_pos.x()) * t
            cy = start_pos.y() + (y - start_pos.y()) * t
            node_item.setPos(cx, cy)

        timeline.frameChanged.connect(_step)

        # Храним ссылку чтобы timeline не удалился сборщиком мусора
        if not hasattr(self, "_animations"):
            self._animations: list[QTimeLine] = []
        self._animations.append(timeline)
        timeline.finished.connect(
            lambda: self._animations.remove(timeline) if timeline in self._animations else None
        )
        timeline.start()

    # ------------------------------------------------------------------
    # Каталог операций
    # ------------------------------------------------------------------

    def set_catalog(self, catalog: dict[str, Any]) -> None:
        """Установить каталог операций без перезагрузки графа.

        Args:
            catalog: словарь type_key → ProcessingOperationDef.
        """
        self._catalog = catalog

    # ------------------------------------------------------------------
    # Drag-drop: приём перетаскивания из CatalogPalette
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        """Принять событие входа drag если MIME совпадает."""
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        """Принять событие перемещения drag если MIME совпадает."""
        if event.mimeData().hasFormat(MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        """Обработать drop: создать новый узел в позиции курсора (snap-to-grid).

        Эмитит сигнал node_added с данными нового узла.
        """
        if not event.mimeData().hasFormat(MIME_TYPE):
            event.ignore()
            return

        # Извлекаем type_key из MIME
        type_key = bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8")
        op_def = self._catalog.get(type_key)
        if op_def is None:
            # Операция не найдена в каталоге — игнорируем
            event.ignore()
            return

        # Позиция на сцене с привязкой к сетке
        pos = event.scenePos()
        snapped_x = round(pos.x() / GRID_SIZE) * GRID_SIZE
        snapped_y = round(pos.y() / GRID_SIZE) * GRID_SIZE

        # Создаём узел с новым UUID
        node_id = str(uuid4())
        self.add_node(node_id, op_def, (snapped_x, snapped_y))

        # Сообщаем внешнему коду о добавлении узла
        self.node_added.emit(
            {
                "node_id": node_id,
                "operation_ref": type_key,
                "position": (snapped_x, snapped_y),
            }
        )

        event.acceptProposedAction()

    # ------------------------------------------------------------------
    # Отрисовка фона с сеткой
    # ------------------------------------------------------------------

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        """Рисуем фон с точечной сеткой."""
        super().drawBackground(painter, rect)

        # Сетка точками
        left = int(rect.left()) - (int(rect.left()) % GRID_SIZE)
        top = int(rect.top()) - (int(rect.top()) % GRID_SIZE)

        pen = QPen(GRID_COLOR, 1.5)
        painter.setPen(pen)

        x = left
        while x < rect.right():
            y = top
            while y < rect.bottom():
                painter.drawPoint(int(x), int(y))
                y += GRID_SIZE
            x += GRID_SIZE

        # Placeholder для пустого графа
        if not self._node_items:
            painter.setPen(QPen(QColor("#666666")))
            painter.setFont(QFont("Segoe UI", 14))
            painter.drawText(
                rect,
                Qt.AlignCenter,
                "Перетащите операцию из каталога",
            )

    # ------------------------------------------------------------------
    # Свойства
    # ------------------------------------------------------------------

    @property
    def node_items(self) -> dict[str, NodeItem]:
        """Словарь node_id → NodeItem (только для чтения)."""
        return dict(self._node_items)

    @property
    def edge_items(self) -> list[EdgeItem]:
        """Список рёбер (только для чтения)."""
        return list(self._edge_items)
