"""GraphView — QGraphicsView с zoom (колесо), pan (средняя кнопка), rubber band."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsView

from .constants import ZOOM_MAX, ZOOM_MIN, ZOOM_STEP
from .graph_scene import GraphScene


class GraphView(QGraphicsView):
    """Обёртка над QGraphicsView для графового редактора.

    Функциональность:
    - Zoom: колесо мыши (scale в пределах [ZOOM_MIN, ZOOM_MAX]).
    - Pan: средняя кнопка мыши (drag).
    - Rubber band: выделение прямоугольником (ЛКМ по умолчанию).
    - Home (клавиша): подогнать вид под все элементы.
    """

    def __init__(self, scene: GraphScene | None = None, parent=None) -> None:
        if scene is not None:
            super().__init__(scene, parent)
        else:
            super().__init__(parent)

        # Текущий уровень zoom
        self._zoom_level = 1.0

        # Рендеринг
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)

        # Режим выделения по умолчанию — rubber band
        self.setDragMode(QGraphicsView.RubberBandDrag)

        # Трансформация относительно курсора
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        # Горизонтальная и вертикальная прокрутка
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Разрешаем приём drag-drop событий (пробрасываются в scene автоматически)
        self.setAcceptDrops(True)

    # ------------------------------------------------------------------
    # Zoom: колесо мыши
    # ------------------------------------------------------------------

    def wheelEvent(self, event) -> None:  # noqa: N802
        """Масштабирование колесом мыши."""
        factor = ZOOM_STEP if event.angleDelta().y() > 0 else 1.0 / ZOOM_STEP

        new_zoom = self._zoom_level * factor

        # Ограничиваем диапазон
        if new_zoom < ZOOM_MIN or new_zoom > ZOOM_MAX:
            return

        self._zoom_level = new_zoom
        self.scale(factor, factor)

    # ------------------------------------------------------------------
    # Pan: средняя кнопка мыши
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Переключение на ScrollHandDrag при нажатии средней кнопки."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            # Qt6 QMouseEvent: 6-arg форма с globalPosition (5-arg deprecated)
            fake_event = event.__class__(
                event.type(),
                event.position(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mousePressEvent(fake_event)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        """Возврат к RubberBandDrag при отпускании средней кнопки."""
        if event.button() == Qt.MouseButton.MiddleButton:
            fake_event = event.__class__(
                event.type(),
                event.position(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mouseReleaseEvent(fake_event)
            self.setDragMode(QGraphicsView.RubberBandDrag)
            return
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Горячие клавиши
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Горячие клавиши: Home — подогнать вид, Delete — удалить выделенное."""
        if event.key() == Qt.Key_Home:
            self.fit_all()
            return
        if event.key() == Qt.Key_Delete:
            self._delete_selected()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        """Контекстное меню: для пустого места показываем меню вида."""
        # Сначала пробуем обработать в scene (NodeItem / EdgeItem)
        # GraphScene.contextMenuEvent вызовет event.ignore() если под курсором пусто
        super().contextMenuEvent(event)

        if not event.isAccepted():
            from .context_menu import show_scene_context_menu

            show_scene_context_menu(self, event.globalPosition().toPoint())

    # ------------------------------------------------------------------
    # Удаление выделенных элементов
    # ------------------------------------------------------------------

    def _delete_selected(self) -> None:
        """Удалить все выделенные узлы и рёбра."""
        scene = self.scene()
        if scene is not None and hasattr(scene, "delete_selected"):
            scene.delete_selected()

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def fit_all(self) -> None:
        """Подогнать вид, чтобы все элементы были видны."""
        scene = self.scene()
        if scene is None:
            return
        bounds = scene.itemsBoundingRect()
        if bounds.isEmpty():
            return
        # Добавляем небольшой отступ
        margins = 40
        bounds.adjust(-margins, -margins, margins, margins)
        self.fitInView(bounds, Qt.KeepAspectRatio)

        # Пересчитываем zoom_level на основе текущего масштаба
        self._zoom_level = self.transform().m11()

    def reset_zoom(self) -> None:
        """Сбросить zoom к 1.0."""
        self.resetTransform()
        self._zoom_level = 1.0

    @property
    def zoom_level(self) -> float:
        """Текущий уровень масштабирования."""
        return self._zoom_level
