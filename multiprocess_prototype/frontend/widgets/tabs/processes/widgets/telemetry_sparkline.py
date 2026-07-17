# -*- coding: utf-8 -*-
"""TelemetrySparkline — лёгкий график-линия на QPainter (план gui-telemetry-read-model, Task 2.2).

Своя реализация НАМЕРЕННО — план запрещает тащить pyqtgraph/matplotlib
(«новых зависимостей не вводить»). Виджет умеет ровно то, что нужно карточке
процесса: линия по (ts, value) с автошкалой по обеим осям + плейсхолдер «нет
данных», когда точек меньше двух (пусто / VM=None / БД без строк — деградирует
gracefully, без падений).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

# Цвета согласованы с остальной палитрой вкладки «Процессы»
# (_SELECTED_CARD_QSS использует #2563eb, health-предупреждения — #dc2626).
_LINE_COLOR = QColor("#2563eb")
_PLACEHOLDER_COLOR = QColor("#94a3b8")
_MARGIN = 4.0


class TelemetrySparkline(QWidget):
    """Мини-график линии метрики по времени (спарклайн)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: list[tuple[float, float]] = []
        self.setMinimumHeight(56)
        self.setMinimumWidth(160)

    def set_points(self, points: list[tuple[float, float]]) -> None:
        """Задать точки (ts, value) — только числовые value, остальное отбрасывается.

        Порядок не переупорядочивается (источники уже отдают хронологический
        порядок — ring-буфер VM и ``TelemetryHistorySource.list_range``).
        """
        self._points = [(t, v) for t, v in points if isinstance(v, (int, float)) and not isinstance(v, bool)]
        self.update()

    def points(self) -> list[tuple[float, float]]:
        """Текущие точки (для тестов/диагностики)."""
        return list(self._points)

    def paintEvent(self, event: object) -> None:  # noqa: N802 — Qt override, ARG002 не нужен
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            if len(self._points) < 2:
                self._paint_placeholder(painter)
            else:
                self._paint_line(painter)
        finally:
            painter.end()

    def _paint_placeholder(self, painter: QPainter) -> None:
        painter.setPen(QPen(_PLACEHOLDER_COLOR))
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "нет данных")

    def _paint_line(self, painter: QPainter) -> None:
        rect = QRectF(self.rect()).adjusted(_MARGIN, _MARGIN, -_MARGIN, -_MARGIN)
        xs = [p[0] for p in self._points]
        ys = [p[1] for p in self._points]
        x_min, x_max = min(xs), max(xs)
        y_min, y_max = min(ys), max(ys)
        # Вырожденный диапазон (все точки на одном ts/value) — раздвигаем на
        # единицу, чтобы не делить на ноль (плоская линия по центру области).
        if x_max == x_min:
            x_max = x_min + 1.0
        if y_max == y_min:
            y_min -= 0.5
            y_max += 0.5

        def to_px(t: float, v: float) -> QPointF:
            x = rect.left() + (t - x_min) / (x_max - x_min) * rect.width()
            y = rect.top() + rect.height() - (v - y_min) / (y_max - y_min) * rect.height()
            return QPointF(x, y)

        path = QPainterPath()
        path.moveTo(to_px(*self._points[0]))
        for t, v in self._points[1:]:
            path.lineTo(to_px(t, v))

        painter.setPen(QPen(_LINE_COLOR, 1.5))
        painter.drawPath(path)


__all__ = ["TelemetrySparkline"]
