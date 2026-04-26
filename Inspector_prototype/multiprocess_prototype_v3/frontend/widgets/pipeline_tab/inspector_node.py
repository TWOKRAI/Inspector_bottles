"""InspectorBaseNode — subclass NodeGraphQt BaseNode с live-preview thumbnail.

Архитектурное решение (Task 9.8): QGraphicsPixmapItem overlay вместо paint() override.
NodeGraphQt NodeItem.paint() содержит сложную логику selection/hover/border/proxy mode,
override которой ломает фичи (Issue #491). QGraphicsPixmapItem — дочерний элемент
NodeItem — рисуется независимо от paint(), не вмешивается в selection highlight.

Ответственность:
- Показывать/скрывать thumbnail для preview-capable операций.
- Принимать QPixmap через update_thumbnail() (слот для NodePreviewBridge).
- Расширять размер ноды (высоту) для размещения thumbnail.
- Флаг display_capable: False → thumbnail не появляется вовсе.

# TODO(framework): кандидат на миграцию — паттерн «overlay QGraphicsItem для
# embedded visualizations в NodeGraphQt нодах». Можно обобщить для любых
# preview/indicator overlays (статус, метрики, sparklines).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from NodeGraphQt import BaseNode
from NodeGraphQt.qgraphics.node_base import NodeItem

from frontend.widgets.pipeline_tab.constants import (
    THUMBNAIL_HEIGHT,
    THUMBNAIL_WIDTH,
    THUMBNAIL_Z_OFFSET,
)

if TYPE_CHECKING:
    from PySide6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger(__name__)


class InspectorNodeItem(NodeItem):
    """Расширенный QGraphicsItem ноды с thumbnail overlay.

    Наследуется от NodeItem (NodeGraphQt), добавляет QGraphicsPixmapItem
    для отображения live-preview кадра. Thumbnail рисуется ниже портов,
    расширяя высоту ноды.
    """

    def __init__(self, name: str = "node", parent: QtWidgets.QGraphicsItem | None = None) -> None:
        super().__init__(name, parent)
        # Lazy import — PySide6 может не быть в тестах
        from PySide6 import QtCore, QtGui, QtWidgets as QtW

        # Thumbnail overlay — child QGraphicsItem, НЕ paint() override
        self._thumbnail_item = QtW.QGraphicsPixmapItem(self)
        self._thumbnail_item.setTransformationMode(QtCore.Qt.SmoothTransformation)
        self._thumbnail_item.setZValue(THUMBNAIL_Z_OFFSET)
        self._thumbnail_item.setVisible(False)

        # Флаг: может ли эта нода показывать thumbnail
        self._display_capable: bool = False
        # Флаг: включено ли preview (можно отключать runtime)
        self._preview_active: bool = False

    # ------------------------------------------------------------------
    # Публичное API
    # ------------------------------------------------------------------

    def set_display_capable(self, capable: bool) -> None:
        """Установить, способна ли нода показывать preview.

        Вызывается при создании ноды из каталога (display_capable из YAML).
        Если False — thumbnail вообще не отображается.

        Args:
            capable: True если операция поддерживает preview.
        """
        self._display_capable = capable
        if not capable:
            self._thumbnail_item.setVisible(False)
            self._preview_active = False

    def set_active_preview(self, active: bool) -> None:
        """Включить/выключить показ live-preview.

        Независимо от display_capable — если display_capable=False,
        set_active_preview(True) ничего не делает.

        Args:
            active: True для включения preview.
        """
        if not self._display_capable:
            self._preview_active = False
            self._thumbnail_item.setVisible(False)
            return

        self._preview_active = active
        self._thumbnail_item.setVisible(active and not self._thumbnail_item.pixmap().isNull())

    def update_thumbnail(self, pixmap: QtGui.QPixmap) -> None:
        """Обновить thumbnail-превью.

        Вызывается NodePreviewBridge при получении нового кадра.
        Pixmap уже масштабирован до THUMBNAIL_WIDTH x THUMBNAIL_HEIGHT
        мостом (preview_bridge).

        Args:
            pixmap: Масштабированный QPixmap (160x120).
        """
        if not self._display_capable or not self._preview_active:
            return

        self._thumbnail_item.setPixmap(pixmap)

        # Позиционируем thumbnail ниже основного контента ноды
        self._align_thumbnail()

        if not self._thumbnail_item.isVisible():
            self._thumbnail_item.setVisible(True)

    @property
    def display_capable(self) -> bool:
        """Способна ли нода показывать preview."""
        return self._display_capable

    @property
    def preview_active(self) -> bool:
        """Активен ли preview."""
        return self._preview_active

    @property
    def thumbnail_visible(self) -> bool:
        """Видим ли thumbnail на данный момент."""
        return self._thumbnail_item.isVisible()

    # ------------------------------------------------------------------
    # Позиционирование thumbnail
    # ------------------------------------------------------------------

    def _align_thumbnail(self) -> None:
        """Расположить thumbnail по центру, ниже портов и виджетов."""
        from PySide6 import QtCore

        rect = self.boundingRect()
        thumb_w = self._thumbnail_item.pixmap().width()
        thumb_h = self._thumbnail_item.pixmap().height()

        if thumb_w == 0 or thumb_h == 0:
            return

        # Центрируем по X, смещаем вниз от текущего bounding rect
        x = rect.center().x() - (thumb_w / 2.0)
        y = rect.height() - 4.0  # небольшой отступ снизу от основного контента

        self._thumbnail_item.setPos(x, y)

    def _draw_node_horizontal(self) -> None:
        """Переопределяем для учёта дополнительной высоты thumbnail."""
        # Вызываем оригинальный layout
        super()._draw_node_horizontal()

        # Если thumbnail активен — расширяем высоту ноды
        if self._preview_active and self._display_capable:
            self._height += THUMBNAIL_HEIGHT + 8.0  # +8 для отступов
            self._align_thumbnail()

    def set_proxy_mode(self, mode: bool) -> None:
        """Прячем thumbnail в proxy mode (zoom out)."""
        super().set_proxy_mode(mode)
        # В proxy mode скрываем thumbnail для производительности
        if mode:
            self._thumbnail_item.setVisible(False)
        elif self._preview_active and self._display_capable:
            if not self._thumbnail_item.pixmap().isNull():
                self._thumbnail_item.setVisible(True)


class InspectorBaseNode(BaseNode):
    """Noda Inspector — BaseNode с поддержкой live-preview thumbnail.

    Заменяет стандартный BaseNode в NodeGraphQtAdapter.
    Используется для всех нод pipeline графа.

    Архитектура:
    - InspectorNodeItem (QGraphicsItem) — рисует thumbnail overlay.
    - InspectorBaseNode (NodeObject) — бизнес-логика ноды + bridge-интерфейс.

    Регистрация в NodeGraphQt:
        graph.register_node(InspectorBaseNode)
        node = graph.create_node("inspector.nodes.InspectorNode")
    """

    # Уникальный идентификатор типа для NodeGraphQt registry
    __identifier__ = "inspector.nodes"

    # Имя по умолчанию (переопределяется при create_node(name=...))
    NODE_NAME = "InspectorNode"

    def __init__(self, qgraphics_item: type | None = None) -> None:
        """Инициализация с кастомным InspectorNodeItem вместо NodeItem.

        Args:
            qgraphics_item: Класс QGraphicsItem (по умолчанию InspectorNodeItem).
        """
        super().__init__(qgraphics_item or InspectorNodeItem)

    # ------------------------------------------------------------------
    # Публичный API для NodePreviewBridge и адаптера
    # ------------------------------------------------------------------

    def set_display_capable(self, capable: bool) -> None:
        """Проксирование в InspectorNodeItem.set_display_capable().

        Args:
            capable: True если операция поддерживает preview (из каталога).
        """
        view = self.view
        if hasattr(view, "set_display_capable"):
            view.set_display_capable(capable)

    def set_active_preview(self, active: bool) -> None:
        """Включить/выключить live-preview.

        Args:
            active: True для включения.
        """
        view = self.view
        if hasattr(view, "set_active_preview"):
            view.set_active_preview(active)

    def update_thumbnail(self, pixmap: object) -> None:
        """Обновить thumbnail-превью (QPixmap).

        Args:
            pixmap: Масштабированный QPixmap.
        """
        view = self.view
        if hasattr(view, "update_thumbnail"):
            view.update_thumbnail(pixmap)

    @property
    def display_capable(self) -> bool:
        """Способна ли нода показывать preview."""
        view = self.view
        if hasattr(view, "display_capable"):
            return view.display_capable
        return False

    @property
    def preview_active(self) -> bool:
        """Активен ли preview."""
        view = self.view
        if hasattr(view, "preview_active"):
            return view.preview_active
        return False


__all__ = ["InspectorBaseNode", "InspectorNodeItem"]
