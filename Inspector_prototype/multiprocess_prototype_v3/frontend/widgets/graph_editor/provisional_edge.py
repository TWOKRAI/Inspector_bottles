"""ProvisionalEdge — временная Bezier-линия при drag-создании связи."""

from __future__ import annotations

from PyQt5.QtCore import QPointF, Qt
from PyQt5.QtGui import QPainterPath, QPen
from PyQt5.QtWidgets import QGraphicsPathItem

from .constants import (
    EDGE_MIN_CONTROL_OFFSET,
    EDGE_WIDTH,
    PROVISIONAL_EDGE_COLOR,
    PROVISIONAL_EDGE_INVALID_COLOR,
)
from .port_item import PortItem


class ProvisionalEdge(QGraphicsPathItem):
    """Временная линия от output-порта к курсору при drag-создании связи.

    Рисуется полупрозрачной белой линией, пока пользователь тянет
    от output-порта к потенциальному input-порту.
    """

    def __init__(self, source_port: PortItem) -> None:
        super().__init__()

        self.source_port = source_port
        self._is_invalid = False

        # Стиль: пунктирная полупрозрачная линия
        pen = QPen(PROVISIONAL_EDGE_COLOR, EDGE_WIDTH, Qt.DashLine, Qt.RoundCap)
        self.setPen(pen)

        # Рисуется поверх рёбер, но под нодами
        self.setZValue(-0.5)

    def update_target(self, scene_pos: QPointF) -> None:
        """Обновить конец Bezier-кривой до позиции курсора."""
        start = self.source_port.center_scene_pos()
        end = scene_pos

        dx = abs(end.x() - start.x())
        offset = max(dx / 3.0, EDGE_MIN_CONTROL_OFFSET)

        ctrl1 = QPointF(start.x() + offset, start.y())
        ctrl2 = QPointF(end.x() - offset, end.y())

        path = QPainterPath(start)
        path.cubicTo(ctrl1, ctrl2, end)
        self.setPath(path)

    def set_invalid(self, invalid: bool) -> None:
        """Переключить цвет линии: красный если несовместимый порт под курсором."""
        if invalid == self._is_invalid:
            return
        self._is_invalid = invalid
        color = PROVISIONAL_EDGE_INVALID_COLOR if invalid else PROVISIONAL_EDGE_COLOR
        self.setPen(QPen(color, EDGE_WIDTH, Qt.DashLine, Qt.RoundCap))
