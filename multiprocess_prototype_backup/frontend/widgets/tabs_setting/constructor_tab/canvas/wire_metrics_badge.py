"""WireMetricsBadge — overlay-badge с метриками wire-канала на pipe.

Фаза 6: Live мониторинг.
Позиционируется в midpoint pipe, рисует компактную плашку
"30fps | 5ms | 50%" с полупрозрачным фоном.

Паттерн: QGraphicsRectItem как overlay (аналог InspectorNodeItem
из pipeline_tab — child QGraphicsItem at Z-offset).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPathItem, QGraphicsRectItem


class WireMetricsBadge(QGraphicsRectItem):
    """Компактная плашка с метриками wire-канала.

    Отображает fps, latency_ms и buffer_fill рядом с pipe.
    Скрывается если все метрики равны нулю (wire неактивен).

    Позиционирование: вызов update_position(pipe_item) размещает
    badge в midpoint QPainterPath pipe.
    """

    # Z-offset выше pipe (pipe обычно Z=0..1)
    _Z_OFFSET = 10

    # Визуальные параметры
    _PADDING_H = 6   # горизонтальный padding
    _PADDING_V = 3   # вертикальный padding
    _BG_COLOR = QColor(40, 40, 40, 200)     # полупрозрачный тёмный фон
    _TEXT_COLOR = QColor(204, 204, 204)     # #cccccc
    _BORDER_COLOR = QColor(80, 80, 80, 150)
    _FONT_SIZE = 8
    _BORDER_RADIUS = 3

    def __init__(self, parent: QGraphicsItem | None = None) -> None:
        super().__init__(parent)
        self.setZValue(self._Z_OFFSET)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, False)

        # Текущие метрики
        self._fps: float = 0.0
        self._latency_ms: float = 0.0
        self._buffer_fill: float = 0.0
        self._text: str = ""

        # Шрифт для отрисовки текста
        self._font = QFont("Segoe UI", self._FONT_SIZE)
        self._font_metrics = QFontMetricsF(self._font)

        # Начальное состояние — скрыт (wire ещё не активен)
        self.setVisible(False)

    def update_metrics(self, fps: float, latency_ms: float, buffer_fill: float) -> None:
        """Обновить метрики и перерисовать badge.

        Args:
            fps: Частота кадров/сообщений в секунду.
            latency_ms: Задержка в миллисекундах.
            buffer_fill: Заполненность буфера (0.0-1.0).
        """
        self._fps = fps
        self._latency_ms = latency_ms
        self._buffer_fill = max(0.0, min(1.0, buffer_fill))

        # Скрыть если все метрики нулевые (wire неактивен)
        if fps < 0.1 and latency_ms < 0.1 and buffer_fill < 0.01:
            self.setVisible(False)
            return

        # Форматировать строку метрик для отображения
        self._text = f"{fps:.0f}fps | {latency_ms:.1f}ms | {buffer_fill * 100:.0f}%"

        # Пересчитать размер badge по ширине текста
        text_rect = self._font_metrics.boundingRect(self._text)
        width = text_rect.width() + self._PADDING_H * 2
        height = text_rect.height() + self._PADDING_V * 2
        self.setRect(0, 0, width, height)

        self.setVisible(True)
        self.update()

    def update_position(self, pipe_item: QGraphicsPathItem) -> None:
        """Позиционировать badge в midpoint path pipe.

        Args:
            pipe_item: QGraphicsPathItem — pipe на канвасе.
        """
        if pipe_item is None:
            self.setVisible(False)
            return

        path = pipe_item.path()
        if path.isEmpty():
            self.setVisible(False)
            return

        # Midpoint path (50% длины кривой)
        midpoint = path.pointAtPercent(0.5)

        # Сместить badge чуть выше midpoint pipe
        rect = self.rect()
        x = midpoint.x() - rect.width() / 2
        y = midpoint.y() - rect.height() - 4  # 4px выше pipe

        # Если badge — child item pipe, позиция относительна pipe
        if self.parentItem() == pipe_item:
            self.setPos(x, y)
        else:
            # Конвертировать в координаты сцены если badge не child pipe
            scene_pos = pipe_item.mapToScene(midpoint)
            self.setPos(
                scene_pos.x() - rect.width() / 2,
                scene_pos.y() - rect.height() - 4,
            )

    def paint(self, painter: QPainter, option, widget=None) -> None:
        """Рисовать badge: скруглённый прямоугольник + текст метрик."""
        rect = self.rect()

        # Фон — полупрозрачный тёмный прямоугольник со скруглёнными углами
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self._BG_COLOR))
        painter.setPen(QPen(self._BORDER_COLOR, 0.5))
        painter.drawRoundedRect(rect, self._BORDER_RADIUS, self._BORDER_RADIUS)

        # Текст метрик поверх фона
        painter.setFont(self._font)
        painter.setPen(QPen(self._TEXT_COLOR))
        text_rect = rect.adjusted(
            self._PADDING_H, self._PADDING_V,
            -self._PADDING_H, -self._PADDING_V,
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._text)

    def set_visible_threshold(self, min_fps: float = 0.1) -> None:
        """Установить порог видимости по fps.

        Badge скрывается если fps < threshold (wire неактивен).
        """
        if self._fps < min_fps:
            self.setVisible(False)


__all__ = ["WireMetricsBadge"]
