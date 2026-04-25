"""NodeItem — визуальное представление узла обработки на QGraphicsScene."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from .constants import (
    GRID_SIZE,
    NODE_BG_COLOR,
    NODE_BORDER_COLOR,
    NODE_CORNER_RADIUS,
    NODE_DISABLED_OPACITY,
    NODE_HEADER_COLOR,
    NODE_HEADER_HEIGHT,
    NODE_PADDING_BOTTOM,
    NODE_SELECTED_BORDER,
    NODE_TEXT_COLOR,
    NODE_WIDTH,
    PORT_RADIUS,
    PORT_SPACING,
)
from .port_item import PortItem

if TYPE_CHECKING:
    from .edge_item import EdgeItem


class NodeItem(QGraphicsItem):
    """Графический узел на сцене: заголовок + входные/выходные порты.

    Args:
        node_id: UUID узла (из ProcessingNode.node_id).
        operation_name: человекочитаемое имя операции.
        input_ports_data: список (name, data_type, optional) для входных портов.
        output_ports_data: список (name, data_type, optional) для выходных портов.
        enabled: активен ли узел.
    """

    def __init__(
        self,
        node_id: str,
        operation_name: str,
        input_ports_data: list[tuple[str, str, bool]],
        output_ports_data: list[tuple[str, str, bool]],
        enabled: bool = True,
    ) -> None:
        super().__init__()

        self.node_id = node_id
        self.operation_name = operation_name

        # Шрифт заголовка
        self._header_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        self._header_metrics = QFontMetrics(self._header_font)

        # Вычисляем высоту ноды
        port_count = max(len(input_ports_data), len(output_ports_data), 1)
        self._height = NODE_HEADER_HEIGHT + port_count * PORT_SPACING + NODE_PADDING_BOTTOM
        self._width = NODE_WIDTH

        # Подготовка обрезанного имени для заголовка
        available_text_width = self._width - 16  # отступы по бокам
        self._display_name = self._header_metrics.elidedText(
            operation_name, Qt.ElideRight, available_text_width
        )

        # Флаги: перетаскивание, выделение, уведомление об изменении геометрии
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)

        # Список связанных рёбер (обновляются при перемещении)
        self._edges: list[EdgeItem] = []

        # Создаём порты
        self._input_ports: list[PortItem] = []
        self._output_ports: list[PortItem] = []
        self._create_ports(input_ports_data, is_input=True)
        self._create_ports(output_ports_data, is_input=False)

        # Прозрачность для disabled
        if not enabled:
            self.setOpacity(NODE_DISABLED_OPACITY)

    # ------------------------------------------------------------------
    # Создание портов
    # ------------------------------------------------------------------

    def _create_ports(
        self,
        ports_data: list[tuple[str, str, bool]],
        is_input: bool,
    ) -> None:
        """Создаёт PortItem'ы как дочерние элементы ноды."""
        port_list = self._input_ports if is_input else self._output_ports
        x = -PORT_RADIUS if is_input else self._width + PORT_RADIUS

        for i, (name, data_type, optional) in enumerate(ports_data):
            y = NODE_HEADER_HEIGHT + PORT_SPACING * (i + 0.5)
            port = PortItem(
                port_name=name,
                data_type=data_type,
                is_input=is_input,
                is_optional=optional,
                parent_node_item=self,
            )
            # Позиция задаётся относительно центра ellipse (т.к. rect = -r..+r)
            port.setPos(x, y)
            port_list.append(port)

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def get_port(self, name: str, is_input: bool) -> PortItem | None:
        """Найти порт по имени и направлению."""
        port_list = self._input_ports if is_input else self._output_ports
        for port in port_list:
            if port.port_name == name:
                return port
        return None

    def add_edge(self, edge: EdgeItem) -> None:
        """Зарегистрировать ребро, связанное с этой нодой."""
        if edge not in self._edges:
            self._edges.append(edge)

    def remove_edge(self, edge: EdgeItem) -> None:
        """Убрать ребро из списка связанных."""
        if edge in self._edges:
            self._edges.remove(edge)

    def set_enabled(self, enabled: bool) -> None:
        """Изменить визуальное состояние enabled/disabled."""
        self.setOpacity(1.0 if enabled else NODE_DISABLED_OPACITY)

    @property
    def input_ports(self) -> list[PortItem]:
        return self._input_ports

    @property
    def output_ports(self) -> list[PortItem]:
        return self._output_ports

    # ------------------------------------------------------------------
    # QGraphicsItem overrides
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:  # noqa: N802
        """Область отрисовки ноды (с запасом для рамки выделения)."""
        margin = 2.0
        return QRectF(-margin, -margin, self._width + 2 * margin, self._height + 2 * margin)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionGraphicsItem,
        widget: QWidget | None = None,
    ) -> None:
        """Отрисовка узла: фон, заголовок, рамка выделения."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        body_rect = QRectF(0, 0, self._width, self._height)

        # --- Фон ---
        path = QPainterPath()
        path.addRoundedRect(body_rect, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)
        painter.fillPath(path, QBrush(NODE_BG_COLOR))

        # --- Заголовок ---
        header_rect = QRectF(0, 0, self._width, NODE_HEADER_HEIGHT)
        header_path = QPainterPath()
        header_path.addRoundedRect(header_rect, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)
        # Закрашиваем нижние углы заголовка, чтобы скругление было только сверху
        bottom_patch = QRectF(
            0, NODE_HEADER_HEIGHT - NODE_CORNER_RADIUS, self._width, NODE_CORNER_RADIUS
        )
        header_path.addRect(bottom_patch)
        painter.fillPath(header_path, QBrush(NODE_HEADER_COLOR))

        # Текст заголовка
        painter.setPen(QPen(NODE_TEXT_COLOR))
        painter.setFont(self._header_font)
        text_rect = QRectF(8, 0, self._width - 16, NODE_HEADER_HEIGHT)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._display_name)

        # --- Рамка ---
        border_color = NODE_SELECTED_BORDER if self.isSelected() else NODE_BORDER_COLOR
        border_width = 2.0 if self.isSelected() else 1.0
        painter.setPen(QPen(border_color, border_width))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(body_rect, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)

        # --- Подписи портов ---
        port_font = QFont("Segoe UI", 7)
        painter.setFont(port_font)
        painter.setPen(QPen(QColor("#AAAAAA")))

        for port in self._input_ports:
            py = port.pos().y()
            painter.drawText(
                QRectF(PORT_RADIUS + 4, py - PORT_SPACING / 2, self._width / 2 - 16, PORT_SPACING),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                port.port_name,
            )

        for port in self._output_ports:
            py = port.pos().y()
            painter.drawText(
                QRectF(
                    self._width / 2,
                    py - PORT_SPACING / 2,
                    self._width / 2 - PORT_RADIUS - 4,
                    PORT_SPACING,
                ),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                port.port_name,
            )

    def itemChange(self, change, value):  # noqa: N802
        """Обработка перемещения: snap-to-grid + обновление рёбер."""
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Snap-to-grid
            new_pos = value
            snapped_x = round(new_pos.x() / GRID_SIZE) * GRID_SIZE
            snapped_y = round(new_pos.y() / GRID_SIZE) * GRID_SIZE

            if snapped_x != new_pos.x() or snapped_y != new_pos.y():
                self.setPos(snapped_x, snapped_y)

            # Обновляем связанные рёбра
            for edge in self._edges:
                edge.update_path()

        return super().itemChange(change, value)
