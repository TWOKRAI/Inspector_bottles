"""EdgeItem — визуальное представление связи между портами (Bezier-кривая)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from .constants import (
    EDGE_COLOR,
    EDGE_HOVER_COLOR,
    EDGE_INVALID_COLOR,
    EDGE_MIN_CONTROL_OFFSET,
    EDGE_WIDTH,
)
from .port_item import PortItem


class EdgeItem(QGraphicsPathItem):
    """Bezier-кривая между двумя портами.

    Цвет определяется совместимостью типов данных:
    EDGE_COLOR — нормальное соединение, EDGE_INVALID_COLOR — несовместимые типы.
    """

    def __init__(self, source_port: PortItem, target_port: PortItem) -> None:
        super().__init__()

        self.source_port = source_port
        self.target_port = target_port

        # Определяем валидность по совместимости типов
        self._is_valid = self._check_compatibility()

        # Базовый цвет
        self._base_color = EDGE_COLOR if self._is_valid else EDGE_INVALID_COLOR
        self._hover_color = EDGE_HOVER_COLOR if self._is_valid else EDGE_INVALID_COLOR.lighter(130)

        self.setPen(QPen(self._base_color, EDGE_WIDTH, Qt.SolidLine, Qt.RoundCap))

        # Рёбра рисуются под нодами
        self.setZValue(-1)

        self.setAcceptHoverEvents(True)

        # Регистрируем ребро в нодах
        source_port.parent_node_item.add_edge(self)
        target_port.parent_node_item.add_edge(self)

        # Первичный расчёт пути
        self.update_path()

    # ------------------------------------------------------------------
    # Совместимость типов
    # ------------------------------------------------------------------

    def _check_compatibility(self) -> bool:
        """Проверяет совместимость типов данных между портами."""
        # Ленивый импорт, чтобы не создавать циклическую зависимость
        from registers.processor.catalog.port_types import are_ports_compatible

        return are_ports_compatible(self.source_port.data_type, self.target_port.data_type)

    @property
    def is_valid(self) -> bool:
        return self._is_valid

    # ------------------------------------------------------------------
    # Bezier-путь
    # ------------------------------------------------------------------

    def update_path(self) -> None:
        """Пересчитать Bezier-кривую между позициями портов."""
        start = self.source_port.center_scene_pos()
        end = self.target_port.center_scene_pos()

        # Контрольные точки: горизонтальный offset (1/3 расстояния, мин. 50px)
        dx = abs(end.x() - start.x())
        offset = max(dx / 3.0, EDGE_MIN_CONTROL_OFFSET)

        ctrl1 = QPointF(start.x() + offset, start.y())
        ctrl2 = QPointF(end.x() - offset, end.y())

        path = QPainterPath(start)
        path.cubicTo(ctrl1, ctrl2, end)
        self.setPath(path)

    # ------------------------------------------------------------------
    # Hover-эффекты
    # ------------------------------------------------------------------

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        """Утолщение при наведении."""
        self.setPen(QPen(self._hover_color, EDGE_WIDTH * 2, Qt.SolidLine, Qt.RoundCap))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        """Возврат к обычной толщине."""
        self.setPen(QPen(self._base_color, EDGE_WIDTH, Qt.SolidLine, Qt.RoundCap))
        super().hoverLeaveEvent(event)

    # ------------------------------------------------------------------
    # Очистка
    # ------------------------------------------------------------------

    def detach(self) -> None:
        """Отсоединить ребро от родительских нод (при удалении)."""
        self.source_port.parent_node_item.remove_edge(self)
        self.target_port.parent_node_item.remove_edge(self)
