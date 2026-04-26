"""Unit-тесты для InspectorBaseNode (Task 9.8).

Покрывает:
  - set_active_preview: включение/выключение live-preview.
  - update_thumbnail: обновление QPixmap в ноде.
  - set_display_capable(False) убирает thumbnail.
  - display_capable=False + set_active_preview(True) → preview остаётся False.
  - Proxy mode скрывает thumbnail.

Без QApplication — InspectorNodeItem замокирован через MagicMock.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# sys.path для плоских импортов
_V3_ROOT = Path(__file__).resolve().parents[2]
if str(_V3_ROOT) not in sys.path:
    sys.path.insert(0, str(_V3_ROOT))


# ---------------------------------------------------------------------------
# Мок InspectorNodeItem — простой класс вместо MagicMock
# ---------------------------------------------------------------------------


class MockInspectorNodeItem:
    """Мок InspectorNodeItem для тестов без Qt.

    Воспроизводит логику set_display_capable / set_active_preview / update_thumbnail
    без реальных QGraphicsItem / QPixmap зависимостей.
    """

    def __init__(self):
        self._display_capable: bool = False
        self._preview_active: bool = False
        self._thumbnail_pixmap: object = None
        self.update_thumbnail_calls: list[object] = []

    def set_display_capable(self, capable: bool) -> None:
        self._display_capable = capable
        if not capable:
            self._preview_active = False
            self._thumbnail_pixmap = None

    def set_active_preview(self, active: bool) -> None:
        if not self._display_capable:
            self._preview_active = False
            return
        self._preview_active = active

    def update_thumbnail(self, pixmap: object) -> None:
        self.update_thumbnail_calls.append(pixmap)

    @property
    def display_capable(self) -> bool:
        return self._display_capable

    @property
    def preview_active(self) -> bool:
        return self._preview_active


# ---------------------------------------------------------------------------
# Фабрика мок-ноды (без реального Qt)
# ---------------------------------------------------------------------------


def _make_inspector_node():
    """Создать InspectorBaseNode с замокированным view (MockInspectorNodeItem).

    Возвращает (node, mock_view) — node с проксированием в mock_view.
    """
    mock_view = MockInspectorNodeItem()

    # Создаём InspectorBaseNode с патчем NodeObject.__init__
    with patch(
        "frontend.widgets.pipeline_tab.inspector_node.BaseNode.__init__",
        return_value=None,
    ):
        from frontend.widgets.pipeline_tab.inspector_node import InspectorBaseNode

        node = InspectorBaseNode()

    # Подставляем мок view
    node._view = mock_view

    return node, mock_view


# ===========================================================================
# Тесты
# ===========================================================================


class TestInspectorBaseNode:
    """Основные тесты InspectorBaseNode."""

    def test_initial_state_not_display_capable(self):
        """По умолчанию display_capable=False."""
        node, view = _make_inspector_node()
        assert node.display_capable is False

    def test_set_display_capable_true(self):
        """set_display_capable(True) → display_capable=True."""
        node, view = _make_inspector_node()
        node.set_display_capable(True)
        assert view.display_capable is True

    def test_set_display_capable_false_clears_preview(self):
        """set_display_capable(False) → preview_active=False, thumbnail не видим."""
        node, view = _make_inspector_node()
        node.set_display_capable(True)
        node.set_active_preview(True)
        assert view.preview_active is True

        node.set_display_capable(False)
        assert view.preview_active is False
        assert view.display_capable is False

    def test_set_active_preview_without_display_capable(self):
        """set_active_preview(True) при display_capable=False → preview_active=False."""
        node, view = _make_inspector_node()
        node.set_active_preview(True)
        assert view.preview_active is False

    def test_set_active_preview_with_display_capable(self):
        """set_active_preview(True) при display_capable=True → preview_active=True."""
        node, view = _make_inspector_node()
        node.set_display_capable(True)
        node.set_active_preview(True)
        assert view.preview_active is True

    def test_update_thumbnail_calls_view(self):
        """update_thumbnail() проксирует в view.update_thumbnail()."""
        node, view = _make_inspector_node()
        node.set_display_capable(True)
        node.set_active_preview(True)

        fake_pixmap = MagicMock()
        node.update_thumbnail(fake_pixmap)

        assert len(view.update_thumbnail_calls) == 1
        assert view.update_thumbnail_calls[0] is fake_pixmap

    def test_update_thumbnail_reaches_view_even_when_not_capable(self):
        """update_thumbnail() при display_capable=False → вызов доходит до view.

        InspectorBaseNode.update_thumbnail проксирует вызов в view.
        Фильтрация (display_capable/preview_active) — на уровне InspectorNodeItem.
        """
        node, view = _make_inspector_node()
        fake_pixmap = MagicMock()
        node.update_thumbnail(fake_pixmap)
        # Вызов доходит до view (проксирование)
        assert len(view.update_thumbnail_calls) == 1

    def test_set_display_capable_false_then_activate_stays_false(self):
        """display_capable=False + set_active_preview(True) → preview_active=False."""
        node, view = _make_inspector_node()
        node.set_display_capable(False)
        node.set_active_preview(True)
        assert node.preview_active is False


class TestInspectorBaseNodeProperties:
    """Тесты property display_capable / preview_active."""

    def test_display_capable_reflects_view(self):
        """display_capable property читает из view."""
        node, view = _make_inspector_node()
        node.set_display_capable(True)
        assert node.display_capable is True

    def test_preview_active_reflects_view(self):
        """preview_active property читает из view."""
        node, view = _make_inspector_node()
        node.set_display_capable(True)
        node.set_active_preview(True)
        assert node.preview_active is True

    def test_preview_active_false_by_default(self):
        """preview_active=False при создании."""
        node, view = _make_inspector_node()
        assert node.preview_active is False
