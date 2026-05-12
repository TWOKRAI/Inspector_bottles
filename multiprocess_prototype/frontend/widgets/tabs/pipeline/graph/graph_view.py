"""GraphView -- QGraphicsView с zoom, pan и wire creation."""
from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsView

from .graph_scene import GraphScene
from .temp_wire import TempWireItem


class InteractionMode(Enum):
    """Режим взаимодействия с графом."""
    SELECT = auto()
    WIRE = auto()


class GraphView(QGraphicsView):
    """View для GraphScene с zoom (колёсиком), pan (средняя кнопка) и wire creation.

    Zoom: wheelEvent с factor 1.15.
    Pan: middleButton drag или ScrollHandDrag.
    Fit: fitInView(scene.itemsBoundingRect()).
    Wire: drag от output порта к input порту.
    """

    ZOOM_FACTOR = 1.15
    ZOOM_MIN = 0.1
    ZOOM_MAX = 5.0

    # Сигнал: (source_endpoint, target_endpoint) при успешном создании wire
    wire_created = Signal(str, str)

    def __init__(self, scene: GraphScene | None = None, parent=None) -> None:
        super().__init__(parent)
        if scene:
            self.setScene(scene)

        # Рендеринг
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Drag mode: rubber band для выделения, middle button для pan
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)

        # Фон (objectName для QSS-правила QGraphicsView#PipelineGraphView)
        self.setObjectName("PipelineGraphView")

        self._current_zoom = 1.0

        # Wire creation state
        self._mode: InteractionMode = InteractionMode.SELECT
        self._temp_wire: TempWireItem | None = None
        self._wire_start_port = None  # PortItem | None

    def wheelEvent(self, event) -> None:
        """Zoom колесом мыши."""
        if event.angleDelta().y() > 0:
            factor = self.ZOOM_FACTOR
        else:
            factor = 1.0 / self.ZOOM_FACTOR

        new_zoom = self._current_zoom * factor
        if self.ZOOM_MIN <= new_zoom <= self.ZOOM_MAX:
            self._current_zoom = new_zoom
            self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        """Начать pan (средняя кнопка) или wire creation (ЛКМ на output порте)."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            fake_event = event.clone()
            super().mousePressEvent(fake_event)
            return

        if event.button() == Qt.MouseButton.LeftButton:
            scene = self.scene()
            if scene and hasattr(scene, "port_at"):
                scene_pos = self.mapToScene(event.pos())
                port = scene.port_at((scene_pos.x(), scene_pos.y()))
                if port and port.is_output:
                    self._mode = InteractionMode.WIRE
                    self._wire_start_port = port
                    start = port.center_scene_pos()
                    self._temp_wire = TempWireItem(start)
                    scene.addItem(self._temp_wire)
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Обновить TempWireItem при перетаскивании wire."""
        if self._mode == InteractionMode.WIRE and self._temp_wire:
            scene_pos = self.mapToScene(event.pos())
            self._temp_wire.update_end((scene_pos.x(), scene_pos.y()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Завершить wire creation или pan."""
        if self._mode == InteractionMode.WIRE:
            scene = self.scene()
            scene_pos = self.mapToScene(event.pos())

            # Очистить temp wire
            if self._temp_wire and scene:
                scene.removeItem(self._temp_wire)
                self._temp_wire = None

            # Валидация: output -> input, не self-loop
            if scene and hasattr(scene, "port_at"):
                target_port = scene.port_at((scene_pos.x(), scene_pos.y()))
                if (
                    target_port
                    and target_port.is_input
                    and self._wire_start_port
                    and target_port.parentItem() != self._wire_start_port.parentItem()
                ):
                    self.wire_created.emit(
                        self._wire_start_port.endpoint,
                        target_port.endpoint,
                    )

            self._wire_start_port = None
            self._mode = InteractionMode.SELECT
            return

        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        super().mouseReleaseEvent(event)

    def fit_to_view(self) -> None:
        """Подогнать масштаб под содержимое."""
        scene = self.scene()
        if scene and scene.items():
            rect = scene.itemsBoundingRect()
            rect.adjust(-20, -20, 20, 20)  # Отступы
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            # Пересчитать zoom
            transform = self.transform()
            self._current_zoom = transform.m11()

    def zoom_in(self) -> None:
        """Приблизить."""
        new_zoom = self._current_zoom * self.ZOOM_FACTOR
        if new_zoom <= self.ZOOM_MAX:
            self._current_zoom = new_zoom
            self.scale(self.ZOOM_FACTOR, self.ZOOM_FACTOR)

    def zoom_out(self) -> None:
        """Отдалить."""
        factor = 1.0 / self.ZOOM_FACTOR
        new_zoom = self._current_zoom * factor
        if new_zoom >= self.ZOOM_MIN:
            self._current_zoom = new_zoom
            self.scale(factor, factor)
