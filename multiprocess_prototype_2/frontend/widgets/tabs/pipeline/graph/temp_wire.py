"""TempWireItem -- временная wire-связь при drag от порта."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem


class TempWireItem(QGraphicsPathItem):
    """Dashed Bezier от стартовой точки до курсора.

    Используется во время интерактивного создания wire.
    """

    def __init__(self, start_pos: tuple[float, float], parent=None) -> None:
        super().__init__(parent)
        self._start = start_pos

        pen = QPen(QColor("#ffff00"), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        self.setPen(pen)
        self.setZValue(1000)  # Поверх всего

    def update_end(self, end_pos: tuple[float, float]) -> None:
        """Обновить конечную точку (позиция курсора)."""
        sx, sy = self._start
        ex, ey = end_pos
        dx = abs(ex - sx) * 0.5

        path = QPainterPath()
        path.moveTo(QPointF(sx, sy))
        path.cubicTo(
            QPointF(sx + dx, sy),
            QPointF(ex - dx, ey),
            QPointF(ex, ey),
        )
        self.setPath(path)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(self.pen())
        painter.drawPath(self.path())
