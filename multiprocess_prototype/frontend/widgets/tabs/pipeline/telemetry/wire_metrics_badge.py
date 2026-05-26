"""Визуальный overlay-badge для wire-соединений pipeline.

Отображает метрики «fps | latency | fill%» поверх edge-линии.
Цвет фона определяется состоянием WireStatus (ok/idle/error).

Используется в Task 7b.3 (WireMetricsController) как дочерний QGraphicsItem
для сцены pipeline-графа.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem

from .wire_metrics_model import WireMetrics, WireStatus

# ---------------------------------------------------------------------------
# Константы геометрии и стилей
# ---------------------------------------------------------------------------

BADGE_WIDTH: int = 100
"""Ширина badge в пикселях. Чуть шире 80 для корректного fit текста."""

BADGE_HEIGHT: int = 24
"""Высота badge в пикселях."""

BADGE_CORNER_RADIUS: int = 6
"""Радиус закруглённых углов badge."""

BADGE_Z_VALUE: float = 10.0
"""Z-значение: badge должен быть выше edges (обычно 0) и nodes (~1)."""

STATUS_COLORS: dict[str, str] = {
    "ok": "#2e7d32",  # Зелёный — активное соединение
    "idle": "#757575",  # Серый — неактивное соединение
    "error": "#c62828",  # Красный — ошибка
}
"""Цвета фона badge по состоянию WireStatus."""

DEFAULT_TEXT: str = "-- fps | -- ms | --%"
"""Текст по умолчанию до первого обновления метрик."""


# ---------------------------------------------------------------------------
# Класс badge
# ---------------------------------------------------------------------------


class WireMetricsBadge(QGraphicsRectItem):
    """Overlay-badge на edge pipeline-графа.

    Отображает метрики производительности wire-соединения:
    «{fps}fps | {latency_ms}ms | {buffer_fill%}%»

    Цвет фона меняется по состоянию WireStatus:
    - ok    → зелёный (#2e7d32)
    - idle  → серый   (#757575)
    - error → красный (#c62828)

    Позиционируется по midpoint edge через update_position().
    Прямоугольник центрирован относительно origin (0, 0).

    Args:
        parent: Родительский QGraphicsItem (опционально).
    """

    def __init__(self, parent: QGraphicsRectItem | None = None) -> None:
        """Инициализировать badge со стандартным видом (idle, дефолтный текст).

        Args:
            parent: Родительский QGraphicsItem (опционально).
        """
        # Прямоугольник центрирован относительно origin — удобно для setPos(midpoint)
        super().__init__(
            QRectF(-BADGE_WIDTH / 2, -BADGE_HEIGHT / 2, BADGE_WIDTH, BADGE_HEIGHT),
            parent,
        )

        # Z-значение выше edges и nodes
        self.setZValue(BADGE_Z_VALUE)

        # Тонкая тёмная рамка
        self.setPen(QPen(QColor("#222222"), 0.5))

        # Начальное состояние — idle
        self._state: str = "idle"
        self.setBrush(QBrush(QColor(STATUS_COLORS["idle"])))

        # Дочерний текстовый элемент
        font = QFont()
        font.setPointSize(7)

        self._text_item = QGraphicsTextItem(DEFAULT_TEXT, self)
        self._text_item.setFont(font)
        self._text_item.setDefaultTextColor(QColor("#ffffff"))

        # Центрировать текст внутри badge
        self._center_text()

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _center_text(self) -> None:
        """Пересчитать позицию дочернего text_item для центрирования внутри badge."""
        br = self._text_item.boundingRect()
        self._text_item.setPos(
            -br.width() / 2,
            -br.height() / 2,
        )

    # ------------------------------------------------------------------
    # Отрисовка с закруглёнными углами
    # ------------------------------------------------------------------

    def paint(
        self,
        painter: QPainter,
        option: object,
        widget: object = None,
    ) -> None:
        """Отрисовать badge с закруглёнными углами.

        Переопределяет стандартный paint QGraphicsRectItem для применения
        drawRoundedRect вместо drawRect.

        Args:
            painter: Контекст рисования.
            option: Параметры стиля (не используются).
            widget: Виджет-контейнер (не используется).
        """
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        painter.drawRoundedRect(self.rect(), BADGE_CORNER_RADIUS, BADGE_CORNER_RADIUS)

    # ------------------------------------------------------------------
    # Публичные методы обновления
    # ------------------------------------------------------------------

    def update_position(self, midpoint: QPointF) -> None:
        """Переместить центр badge в указанную точку.

        Вызывается при перемещении узлов или первичном размещении edge.

        Args:
            midpoint: Координаты центра badge в системе сцены.
        """
        self.setPos(midpoint)

    def update_metrics(self, metrics: WireMetrics) -> None:
        """Обновить текст badge по новым метрикам производительности.

        Формат: «{fps:.0f}fps | {latency_ms:.0f}ms | {buffer_fill*100:.0f}%»

        Args:
            metrics: Свежие метрики wire-соединения.
        """
        text = f"{metrics.fps:.0f}fps | {metrics.latency_ms:.0f}ms | {metrics.buffer_fill * 100:.0f}%"
        self._text_item.setPlainText(text)
        self._center_text()

    def update_status(self, status: WireStatus) -> None:
        """Обновить цвет фона badge по новому статусу соединения.

        Args:
            status: Новый статус wire-соединения.
        """
        self._state = status.state
        color = STATUS_COLORS.get(status.state, STATUS_COLORS["idle"])
        self.setBrush(QBrush(QColor(color)))
        self.update()  # Запросить перерисовку

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Текущее состояние badge (ok/idle/error).

        Returns:
            Строка состояния из последнего вызова update_status().
        """
        return self._state
