"""NodePreviewBridge — мост между DisplayRouter и InspectorBaseNode thumbnail.

Подписывается на канал ``node_preview.{node_id}`` в DisplayRouter,
получает кадры, масштабирует до THUMBNAIL_WIDTH x THUMBNAIL_HEIGHT
и передаёт в InspectorBaseNode.update_thumbnail().

Ключевые оптимизации:
- **Viewport culling**: если нода не видна в viewport — подписка приостанавливается.
  Периодическая проверка через QTimer (throttle cycle).
- **FPS throttle**: максимум THUMBNAIL_UPDATE_INTERVAL_MS мс между обновлениями.
  Стратегия latest-frame-wins — промежуточные кадры отбрасываются.
- **Lazy subscribe**: подписка создаётся только когда preview активируется,
  не при создании моста.

Контракт с DisplayRouter:
- subscribe_preview(channel, callback) / unsubscribe_preview(channel)
  добавлены в Task 9.8.
- is_anyone_subscribed(channel) — проверяет наличие подписчиков.

# TODO(framework): возможно стоит добавить UI-throttle helper
# в frontend_module для QTimer-based throttle + latest-frame-wins.
# Паттерн встречается в DisplayWindow, NodePreviewBridge, будущих widgets.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui

from ..constants import (
    THUMBNAIL_HEIGHT,
    THUMBNAIL_UPDATE_INTERVAL_MS,
    THUMBNAIL_WIDTH,
)

if TYPE_CHECKING:
    from frontend.managers.display_router import DisplayRouter
    from frontend.widgets.pipeline.pipeline_tab.inspector.inspector_node import InspectorBaseNode

logger = logging.getLogger(__name__)


class NodePreviewBridge(QtCore.QObject):
    """Мост для доставки live-preview кадров в ноды графа.

    Один экземпляр на один InspectorBaseNode. Управляется адаптером:
    создаётся при add_node, удаляется при remove_node.

    Наследует QObject для поддержки QTimer и корректного lifecycle
    (аналог NodeGraphQtAdapter — QObject-сервис, не BaseWidget).
    """

    def __init__(
        self,
        node: InspectorBaseNode,
        node_id: str,
        display_router: DisplayRouter,
        *,
        parent: QtCore.QObject | None = None,
    ) -> None:
        """Инициализация моста.

        Args:
            node: InspectorBaseNode (целевая нода для thumbnail).
            node_id: Наш UUID node_id (для формирования channel name).
            display_router: DisplayRouter (для subscribe/unsubscribe preview).
            parent: Qt-родитель.
        """
        super().__init__(parent)

        self._node = node
        self._node_id = node_id
        self._display_router = display_router

        # Канал для preview кадров этой ноды
        self._channel = f"node_preview.{node_id}"

        # Подписана ли нода на данный момент
        self._subscribed: bool = False

        # Последний полученный кадр (latest-frame-wins throttle)
        self._pending_pixmap: QtGui.QPixmap | None = None

        # QTimer для throttle — ограничивает частоту обновления thumbnail
        # Используем QTimer (стандартный Qt-путь для UI-thread throttle),
        # а не worker_module — preview rendering в UI process, QTimer оптимален.
        # TODO(framework): возможно стоит добавить UI-throttle helper в frontend_module
        self._throttle_timer = QtCore.QTimer(self)
        self._throttle_timer.setInterval(THUMBNAIL_UPDATE_INTERVAL_MS)
        self._throttle_timer.setSingleShot(False)
        self._throttle_timer.timeout.connect(self._flush_pending_frame)

        # QTimer для viewport culling — периодическая проверка видимости
        self._visibility_timer = QtCore.QTimer(self)
        self._visibility_timer.setInterval(500)  # проверяем раз в 500 мс
        self._visibility_timer.setSingleShot(False)
        self._visibility_timer.timeout.connect(self._check_visibility)

        logger.debug(
            "NodePreviewBridge создан: node_id=%s, channel=%s",
            node_id,
            self._channel,
        )

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def activate(self) -> None:
        """Активировать preview: подписаться на канал, запустить таймеры.

        Вызывается когда pipeline запущен и нода display_capable.
        """
        if not self._node.display_capable:
            logger.debug(
                "activate: нода %s не display_capable, пропуск",
                self._node_id,
            )
            return

        self._node.set_active_preview(True)
        self._subscribe()
        self._throttle_timer.start()
        self._visibility_timer.start()

        logger.debug("NodePreviewBridge активирован: %s", self._node_id)

    def deactivate(self) -> None:
        """Деактивировать preview: отписаться, остановить таймеры."""
        self._throttle_timer.stop()
        self._visibility_timer.stop()
        self._unsubscribe()
        self._node.set_active_preview(False)
        self._pending_pixmap = None

        logger.debug("NodePreviewBridge деактивирован: %s", self._node_id)

    def dispose(self) -> None:
        """Полная очистка: отписка + остановка таймеров + удаление ссылок."""
        self.deactivate()
        self._throttle_timer.deleteLater()
        self._visibility_timer.deleteLater()

    # ------------------------------------------------------------------
    # Callback для DisplayRouter (вызывается из routing thread)
    # ------------------------------------------------------------------

    def on_frame_received(self, frame: object) -> None:
        """Callback при получении кадра из DisplayRouter.

        Вызывается в потоке routing (не UI thread!). Масштабирует кадр
        и сохраняет в pending — UI thread заберёт через QTimer.

        Args:
            frame: numpy ndarray (BGR) или bytes — кадр для thumbnail.
        """
        try:
            pixmap = self._frame_to_pixmap(frame)
            if pixmap is not None:
                self._pending_pixmap = pixmap
        except Exception as exc:
            logger.warning(
                "on_frame_received: ошибка конвертации кадра для %s: %s",
                self._node_id,
                exc,
            )

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    def _subscribe(self) -> None:
        """Подписаться на preview-канал в DisplayRouter."""
        if self._subscribed:
            return

        self._display_router.subscribe_preview(
            self._channel,
            self.on_frame_received,
        )
        self._subscribed = True

    def _unsubscribe(self) -> None:
        """Отписаться от preview-канала."""
        if not self._subscribed:
            return

        self._display_router.unsubscribe_preview(self._channel)
        self._subscribed = False

    def _flush_pending_frame(self) -> None:
        """Отправить последний полученный кадр в ноду (UI thread).

        Вызывается QTimer с частотой THUMBNAIL_UPDATE_INTERVAL_MS.
        Latest-frame-wins: если за интервал пришло N кадров — показываем последний.
        """
        pixmap = self._pending_pixmap
        if pixmap is None:
            return

        self._pending_pixmap = None
        self._node.update_thumbnail(pixmap)

    def _check_visibility(self) -> None:
        """Viewport culling: проверить, видна ли нода в viewport.

        Если нода вышла из viewport — приостановить подписку (экономия CPU).
        Если вернулась — возобновить.
        """
        visible = self._is_node_visible_in_viewport()

        if visible and not self._subscribed:
            # Нода стала видимой — возобновить подписку
            self._subscribe()
            logger.debug(
                "viewport culling: нода %s стала видимой, подписка возобновлена",
                self._node_id,
            )
        elif not visible and self._subscribed:
            # Нода вышла из viewport — приостановить подписку
            self._unsubscribe()
            logger.debug(
                "viewport culling: нода %s не видна, подписка приостановлена",
                self._node_id,
            )

    def _is_node_visible_in_viewport(self) -> bool:
        """Проверить, видна ли нода в текущем viewport.

        Используем scene boundingRect ноды + viewport rect viewer'а.
        Если нода вне viewport — возвращаем False.

        Returns:
            True если нода видна хотя бы частично.
        """
        try:
            view = self._node.view  # InspectorNodeItem (QGraphicsItem)
            scene = view.scene()
            if scene is None:
                return False

            # Получаем viewer (QGraphicsView) через scene.views()
            views = scene.views()
            if not views:
                return False

            viewer = views[0]
            # Viewport rect в scene coordinates
            viewport_rect = viewer.mapToScene(
                viewer.viewport().rect(),
            ).boundingRect()

            # Bounding rect ноды в scene coordinates
            node_rect = view.sceneBoundingRect()

            return viewport_rect.intersects(node_rect)
        except (RuntimeError, AttributeError):
            # Нода или сцена уже удалена — считаем невидимой
            return False

    @staticmethod
    def _frame_to_pixmap(frame: object) -> QtGui.QPixmap | None:
        """Конвертировать numpy ndarray (BGR) в QPixmap, масштабировать.

        Масштабирование до THUMBNAIL_WIDTH x THUMBNAIL_HEIGHT
        происходит здесь (в UI thread при вызове, но фактически вызывается
        из routing thread — масштабирование numpy дешевле чем QPixmap).

        Args:
            frame: numpy ndarray (H, W, 3) в BGR формате.

        Returns:
            QPixmap масштабированный до thumbnail размера, или None при ошибке.
        """
        try:
            import numpy as np

            if not isinstance(frame, np.ndarray):
                return None

            h, w = frame.shape[:2]
            if h == 0 or w == 0:
                return None

            # BGR -> RGB
            if len(frame.shape) == 3 and frame.shape[2] == 3:
                rgb = frame[:, :, ::-1].copy()
            elif len(frame.shape) == 2:
                # Grayscale -> RGB
                rgb = np.stack([frame, frame, frame], axis=2)
            else:
                rgb = frame.copy()

            h, w = rgb.shape[:2]
            bytes_per_line = 3 * w

            image = QtGui.QImage(
                rgb.data,
                w,
                h,
                bytes_per_line,
                QtGui.QImage.Format.Format_RGB888,
            )

            # Масштабируем до thumbnail размера
            scaled = image.scaled(
                THUMBNAIL_WIDTH,
                THUMBNAIL_HEIGHT,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )

            return QtGui.QPixmap.fromImage(scaled)
        except Exception as exc:
            logger.warning("_frame_to_pixmap: ошибка: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def channel(self) -> str:
        """Канал preview для этой ноды."""
        return self._channel

    @property
    def node_id(self) -> str:
        """UUID ноды."""
        return self._node_id

    @property
    def subscribed(self) -> bool:
        """Подписана ли нода на preview канал."""
        return self._subscribed


__all__ = ["NodePreviewBridge"]
