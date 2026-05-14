"""PipelineDropTarget — event filter для приёма D&D плагинов на GraphView."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QEvent, QObject, QPointF

if TYPE_CHECKING:
    from PySide6.QtWidgets import QGraphicsView

from .palette_widget import MIME_TYPE


class PipelineDropTarget(QObject):
    """Event filter на viewport() GraphView для приёма drag-and-drop плагинов.

    Args:
        view: QGraphicsView, на viewport которого ставится фильтр.
        on_drop: callback(plugin_name: str, scene_pos: QPointF) — вызывается при drop.
    """

    def __init__(
        self,
        view: "QGraphicsView",
        on_drop: Callable[[str, QPointF], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or view)
        self._view = view
        self._on_drop = on_drop
        view.viewport().installEventFilter(self)

    def detach(self) -> None:
        """Удалить event filter."""
        vp = self._view.viewport()
        if vp:
            vp.removeEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()

        if etype == QEvent.Type.DragEnter:
            if event.mimeData().hasFormat(MIME_TYPE):
                event.acceptProposedAction()
                return True

        elif etype == QEvent.Type.DragMove:
            if event.mimeData().hasFormat(MIME_TYPE):
                event.acceptProposedAction()
                return True

        elif etype == QEvent.Type.Drop:
            mime = event.mimeData()
            if mime.hasFormat(MIME_TYPE):
                plugin_name = bytes(mime.data(MIME_TYPE)).decode("utf-8")
                # Конвертация viewport coords → scene coords
                viewport_pos = event.position().toPoint()
                scene_pos = self._view.mapToScene(viewport_pos)
                self._on_drop(plugin_name, scene_pos)
                event.acceptProposedAction()
                return True

        return super().eventFilter(obj, event)
