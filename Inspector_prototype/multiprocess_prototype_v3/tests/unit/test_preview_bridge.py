"""Unit-тесты для NodePreviewBridge (Task 9.8).

Покрывает:
  - Viewport culling: подписка приостанавливается когда нода вне viewport.
  - Throttle: pending frame обновляется, flush отправляет последний кадр.
  - Lazy подписка: activate() подписывает, deactivate() отписывает.
  - display_capable=False: activate() пропускается.
  - dispose(): полная очистка.

Без QApplication — QTimer и QObject замокированы.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------


def _make_mock_node(display_capable: bool = True) -> MagicMock:
    """Создать мок InspectorBaseNode."""
    node = MagicMock()
    node.display_capable = display_capable
    node.set_active_preview = MagicMock()
    node.update_thumbnail = MagicMock()

    # view для viewport culling (мок QGraphicsItem)
    mock_view = MagicMock()
    mock_scene = MagicMock()
    mock_viewer = MagicMock()
    mock_viewport = MagicMock()

    # scene().views() → [viewer]
    mock_scene.views.return_value = [mock_viewer]
    mock_view.scene.return_value = mock_scene
    mock_viewer.viewport.return_value = mock_viewport

    # viewport().rect() → QRect mock
    from unittest.mock import PropertyMock
    mock_viewport.rect.return_value = MagicMock()

    # mapToScene → возвращает мок с boundingRect
    mock_mapped = MagicMock()
    mock_mapped.boundingRect.return_value = MagicMock(
        intersects=MagicMock(return_value=True),
    )
    mock_viewer.mapToScene.return_value = mock_mapped

    # sceneBoundingRect
    mock_view.sceneBoundingRect.return_value = MagicMock()

    node.view = mock_view

    return node


def _make_mock_display_router() -> MagicMock:
    """Создать мок DisplayRouter."""
    dr = MagicMock()
    dr.subscribe_preview = MagicMock()
    dr.unsubscribe_preview = MagicMock()
    dr.is_anyone_subscribed = MagicMock(return_value=True)
    return dr


def _create_bridge(
    *,
    display_capable: bool = True,
    node_id: str = "test-node-123",
):
    """Создать NodePreviewBridge с замокированными зависимостями.

    Возвращает (bridge, node_mock, display_router_mock).
    """
    node = _make_mock_node(display_capable=display_capable)
    dr = _make_mock_display_router()

    # Патчим QObject.__init__ и QTimer чтобы не требовать QApplication
    with patch(
        "frontend.widgets.pipeline_tab.preview_bridge.QtCore.QObject.__init__",
        return_value=None,
    ), patch(
        "frontend.widgets.pipeline_tab.preview_bridge.QtCore.QTimer",
    ) as MockTimer:
        # QTimer mock — возвращает мок с start/stop/setInterval/timeout/connect
        timer_instances = []

        def timer_factory(*args, **kwargs):
            t = MagicMock()
            t.timeout = MagicMock()
            t.timeout.connect = MagicMock()
            timer_instances.append(t)
            return t

        MockTimer.side_effect = timer_factory

        from frontend.widgets.pipeline_tab.preview_bridge import NodePreviewBridge

        bridge = NodePreviewBridge(
            node=node,
            node_id=node_id,
            display_router=dr,
        )

    # Привязываем мок таймеры
    if len(timer_instances) >= 2:
        bridge._throttle_timer = timer_instances[0]
        bridge._visibility_timer = timer_instances[1]

    return bridge, node, dr


# ===========================================================================
# Тесты
# ===========================================================================


class TestNodePreviewBridgeActivation:
    """Тесты активации/деактивации preview."""

    def test_activate_subscribes_to_channel(self):
        """activate() → subscribe_preview вызван с правильным channel."""
        bridge, node, dr = _create_bridge()
        bridge.activate()

        dr.subscribe_preview.assert_called_once_with(
            "node_preview.test-node-123",
            bridge.on_frame_received,
        )

    def test_activate_starts_timers(self):
        """activate() → throttle_timer и visibility_timer запущены."""
        bridge, node, dr = _create_bridge()
        bridge.activate()

        bridge._throttle_timer.start.assert_called_once()
        bridge._visibility_timer.start.assert_called_once()

    def test_activate_sets_active_preview(self):
        """activate() → node.set_active_preview(True) вызван."""
        bridge, node, dr = _create_bridge()
        bridge.activate()

        node.set_active_preview.assert_called_with(True)

    def test_activate_not_display_capable_skips(self):
        """activate() при display_capable=False → subscribe не вызван."""
        bridge, node, dr = _create_bridge(display_capable=False)
        bridge.activate()

        dr.subscribe_preview.assert_not_called()
        bridge._throttle_timer.start.assert_not_called()

    def test_deactivate_unsubscribes(self):
        """deactivate() → unsubscribe_preview вызван."""
        bridge, node, dr = _create_bridge()
        bridge.activate()
        bridge.deactivate()

        dr.unsubscribe_preview.assert_called_once_with(
            "node_preview.test-node-123",
        )

    def test_deactivate_stops_timers(self):
        """deactivate() → оба таймера остановлены."""
        bridge, node, dr = _create_bridge()
        bridge.activate()
        bridge.deactivate()

        bridge._throttle_timer.stop.assert_called_once()
        bridge._visibility_timer.stop.assert_called_once()

    def test_deactivate_sets_preview_false(self):
        """deactivate() → node.set_active_preview(False) вызван."""
        bridge, node, dr = _create_bridge()
        bridge.activate()
        bridge.deactivate()

        node.set_active_preview.assert_called_with(False)


class TestNodePreviewBridgeThrottle:
    """Тесты throttle (latest-frame-wins)."""

    def test_on_frame_received_stores_pending(self):
        """on_frame_received() сохраняет pixmap в pending."""
        bridge, node, dr = _create_bridge()

        # Мокаем _frame_to_pixmap
        fake_pixmap = MagicMock()
        with patch.object(
            type(bridge),
            "_frame_to_pixmap",
            staticmethod(lambda frame: fake_pixmap),
        ):
            import numpy as np
            bridge.on_frame_received(np.zeros((100, 100, 3), dtype="uint8"))

        assert bridge._pending_pixmap is fake_pixmap

    def test_flush_pending_sends_to_node(self):
        """_flush_pending_frame() отправляет pending pixmap в ноду."""
        bridge, node, dr = _create_bridge()

        fake_pixmap = MagicMock()
        bridge._pending_pixmap = fake_pixmap

        bridge._flush_pending_frame()

        node.update_thumbnail.assert_called_once_with(fake_pixmap)
        assert bridge._pending_pixmap is None

    def test_flush_no_pending_does_nothing(self):
        """_flush_pending_frame() без pending → update_thumbnail не вызван."""
        bridge, node, dr = _create_bridge()
        bridge._flush_pending_frame()
        node.update_thumbnail.assert_not_called()

    def test_latest_frame_wins(self):
        """Несколько on_frame_received → flush отдаёт только последний."""
        bridge, node, dr = _create_bridge()

        pixmap1 = MagicMock(name="pixmap1")
        pixmap2 = MagicMock(name="pixmap2")
        pixmap3 = MagicMock(name="pixmap3")

        with patch.object(type(bridge), "_frame_to_pixmap", staticmethod(lambda f: f)):
            bridge.on_frame_received(pixmap1)
            bridge.on_frame_received(pixmap2)
            bridge.on_frame_received(pixmap3)

        bridge._flush_pending_frame()
        node.update_thumbnail.assert_called_once_with(pixmap3)


class TestNodePreviewBridgeViewportCulling:
    """Тесты viewport culling."""

    def test_check_visibility_visible_stays_subscribed(self):
        """Нода видна в viewport → подписка сохраняется."""
        bridge, node, dr = _create_bridge()
        bridge.activate()

        # Мокаем _is_node_visible_in_viewport = True
        with patch.object(bridge, "_is_node_visible_in_viewport", return_value=True):
            bridge._check_visibility()

        # Подписка не менялась (уже подписан, видим)
        assert bridge._subscribed is True

    def test_check_visibility_not_visible_unsubscribes(self):
        """Нода вне viewport → подписка приостанавливается."""
        bridge, node, dr = _create_bridge()
        bridge.activate()

        with patch.object(bridge, "_is_node_visible_in_viewport", return_value=False):
            bridge._check_visibility()

        assert bridge._subscribed is False
        dr.unsubscribe_preview.assert_called()

    def test_check_visibility_becomes_visible_resubscribes(self):
        """Нода возвращается в viewport → подписка возобновляется."""
        bridge, node, dr = _create_bridge()
        bridge.activate()

        # Скрываем
        with patch.object(bridge, "_is_node_visible_in_viewport", return_value=False):
            bridge._check_visibility()
        assert bridge._subscribed is False

        # Показываем
        with patch.object(bridge, "_is_node_visible_in_viewport", return_value=True):
            bridge._check_visibility()
        assert bridge._subscribed is True


class TestNodePreviewBridgeDispose:
    """Тесты полной очистки."""

    def test_dispose_cleans_up(self):
        """dispose() → deactivate + deleteLater таймеров."""
        bridge, node, dr = _create_bridge()
        bridge.activate()
        bridge.dispose()

        bridge._throttle_timer.stop.assert_called()
        bridge._visibility_timer.stop.assert_called()
        bridge._throttle_timer.deleteLater.assert_called_once()
        bridge._visibility_timer.deleteLater.assert_called_once()


class TestNodePreviewBridgeProperties:
    """Тесты read-only properties."""

    def test_channel_format(self):
        """channel = 'node_preview.{node_id}'."""
        bridge, _, _ = _create_bridge(node_id="abc-123")
        assert bridge.channel == "node_preview.abc-123"

    def test_node_id(self):
        """node_id возвращает переданный UUID."""
        bridge, _, _ = _create_bridge(node_id="xyz-999")
        assert bridge.node_id == "xyz-999"

    def test_subscribed_after_activate(self):
        """subscribed=True после activate()."""
        bridge, _, _ = _create_bridge()
        bridge.activate()
        assert bridge.subscribed is True

    def test_subscribed_after_deactivate(self):
        """subscribed=False после deactivate()."""
        bridge, _, _ = _create_bridge()
        bridge.activate()
        bridge.deactivate()
        assert bridge.subscribed is False
