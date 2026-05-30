"""PipelineDropTarget — event filter для приёма D&D плагинов на GraphView."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QEvent, QObject, QPointF

if TYPE_CHECKING:
    from PySide6.QtWidgets import QGraphicsView

from .palette_widget import MIME_TYPE, MIME_TYPE_DISPLAY


class PipelineDropTarget(QObject):
    """Event filter на viewport() GraphView для приёма drag-and-drop из палитры.

    Принимает два типа: плагины (MIME_TYPE → on_drop) и дисплеи
    (MIME_TYPE_DISPLAY → on_display_drop).

    Args:
        view: QGraphicsView, на viewport которого ставится фильтр.
        on_drop: callback(plugin_name: str, scene_pos: QPointF) — drop плагина.
        on_display_drop: callback(display_id: str, scene_pos: QPointF) — drop дисплея
            (опционально; если None — display-drop игнорируется).
    """

    def __init__(
        self,
        view: "QGraphicsView",
        on_drop: Callable[[str, QPointF], None],
        on_display_drop: Callable[[str, QPointF], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or view)
        self._view = view
        self._on_drop = on_drop
        self._on_display_drop = on_display_drop
        view.viewport().installEventFilter(self)

    def _accepted_formats(self) -> tuple[str, ...]:
        """MIME-форматы, которые фильтр принимает (display — только если есть callback)."""
        if self._on_display_drop is not None:
            return (MIME_TYPE, MIME_TYPE_DISPLAY)
        return (MIME_TYPE,)

    def detach(self) -> None:
        """Удалить event filter."""
        vp = self._view.viewport()
        if vp:
            vp.removeEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        etype = event.type()
        formats = self._accepted_formats()

        if etype in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            if any(event.mimeData().hasFormat(fmt) for fmt in formats):
                event.acceptProposedAction()
                return True

        elif etype == QEvent.Type.Drop:
            mime = event.mimeData()
            # Конвертация viewport coords → scene coords
            scene_pos = self._view.mapToScene(event.position().toPoint())

            if mime.hasFormat(MIME_TYPE):
                plugin_name = bytes(mime.data(MIME_TYPE)).decode("utf-8")
                self._on_drop(plugin_name, scene_pos)
                event.acceptProposedAction()
                return True

            if self._on_display_drop is not None and mime.hasFormat(MIME_TYPE_DISPLAY):
                display_id = bytes(mime.data(MIME_TYPE_DISPLAY)).decode("utf-8")
                self._on_display_drop(display_id, scene_pos)
                event.acceptProposedAction()
                return True

        return super().eventFilter(obj, event)
