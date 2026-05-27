"""Тесты для WireMetricsBadge — overlay-badge на edge pipeline-графа.

Проверяют:
- корректное создание badge с дефолтными значениями
- обновление текста при вызове update_metrics()
- смену цвета фона при вызове update_status() для всех состояний
- позиционирование через update_position()
- добавление в QGraphicsScene
- Z-значение выше дефолтного
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsScene

from multiprocess_prototype.frontend.widgets.tabs.pipeline.telemetry.wire_metrics_badge import (
    BADGE_Z_VALUE,
    DEFAULT_TEXT,
    STATUS_COLORS,
    WireMetricsBadge,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.telemetry.wire_metrics_model import (
    WireMetrics,
    WireStatus,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def badge(qtbot):
    """Создать WireMetricsBadge (qtbot обеспечивает QApplication)."""
    return WireMetricsBadge()


# ---------------------------------------------------------------------------
# Тест 1: дефолтное создание
# ---------------------------------------------------------------------------


class TestBadgeCreation:
    """Тесты инициализации badge с дефолтными значениями."""

    def test_badge_creation_default_text(self, badge):
        """Badge создаётся с дефолтным текстом и состоянием idle."""
        assert badge._text_item.toPlainText() == DEFAULT_TEXT
        assert badge.state == "idle"

    def test_badge_zvalue_above_default(self, badge):
        """Z-значение badge равно BADGE_Z_VALUE (10.0) — выше дефолтного нуля."""
        assert badge.zValue() == BADGE_Z_VALUE
        # Явная проверка что Z больше 0 (дефолтное для QGraphicsItem)
        assert badge.zValue() > 0.0

    def test_badge_initial_color_is_idle(self, badge):
        """Badge создаётся с цветом idle (#757575)."""
        color = badge.brush().color().name().lower()
        assert color == STATUS_COLORS["idle"].lower()


# ---------------------------------------------------------------------------
# Тест 2: обновление метрик
# ---------------------------------------------------------------------------


class TestUpdateMetrics:
    """Тесты обновления текста через update_metrics()."""

    def test_badge_update_metrics_changes_text(self, badge):
        """update_metrics() форматирует и отображает корректный текст."""
        metrics = WireMetrics(fps=30.0, latency_ms=5.0, buffer_fill=0.5)
        badge.update_metrics(metrics)
        text = badge._text_item.toPlainText()
        assert "30fps" in text
        assert "5ms" in text
        assert "50%" in text

    def test_badge_update_metrics_zero_values(self, badge):
        """update_metrics() корректно обрабатывает нулевые значения."""
        metrics = WireMetrics(fps=0.0, latency_ms=0.0, buffer_fill=0.0)
        badge.update_metrics(metrics)
        text = badge._text_item.toPlainText()
        assert "0fps" in text
        assert "0ms" in text
        assert "0%" in text

    def test_badge_update_metrics_rounds_values(self, badge):
        """update_metrics() округляет значения до целых."""
        metrics = WireMetrics(fps=29.7, latency_ms=4.4, buffer_fill=0.756)
        badge.update_metrics(metrics)
        text = badge._text_item.toPlainText()
        assert "30fps" in text
        assert "4ms" in text
        assert "76%" in text


# ---------------------------------------------------------------------------
# Тест 3: смена цвета по статусу
# ---------------------------------------------------------------------------


class TestUpdateStatus:
    """Тесты смены цвета фона через update_status()."""

    def test_badge_update_status_ok_changes_color(self, badge):
        """update_status(ok) меняет цвет фона на зелёный (#2e7d32)."""
        badge.update_status(WireStatus(state="ok"))
        color = badge.brush().color().name().lower()
        assert color == STATUS_COLORS["ok"].lower()
        assert badge.state == "ok"

    def test_badge_update_status_idle_changes_color(self, badge):
        """update_status(idle) меняет цвет фона на серый (#757575)."""
        # Сначала переведём в ok, потом обратно в idle
        badge.update_status(WireStatus(state="ok"))
        badge.update_status(WireStatus(state="idle"))
        color = badge.brush().color().name().lower()
        assert color == STATUS_COLORS["idle"].lower()
        assert badge.state == "idle"

    def test_badge_update_status_error_changes_color(self, badge):
        """update_status(error) меняет цвет фона на красный (#c62828)."""
        badge.update_status(WireStatus(state="error"))
        color = badge.brush().color().name().lower()
        assert color == STATUS_COLORS["error"].lower()
        assert badge.state == "error"


# ---------------------------------------------------------------------------
# Тест 4: позиционирование
# ---------------------------------------------------------------------------


class TestBadgePosition:
    """Тесты позиционирования badge через update_position()."""

    def test_badge_position(self, badge):
        """update_position() устанавливает позицию badge в указанную точку."""
        target = QPointF(100.0, 50.0)
        badge.update_position(target)
        assert badge.pos() == target

    def test_badge_position_origin(self, badge):
        """update_position(0, 0) устанавливает badge в начало координат."""
        badge.update_position(QPointF(0.0, 0.0))
        assert badge.pos() == QPointF(0.0, 0.0)

    def test_badge_position_negative(self, badge):
        """update_position() корректно обрабатывает отрицательные координаты."""
        target = QPointF(-50.0, -25.0)
        badge.update_position(target)
        assert badge.pos() == target


# ---------------------------------------------------------------------------
# Тест 5: добавление в сцену
# ---------------------------------------------------------------------------


class TestBadgeScene:
    """Тесты интеграции badge с QGraphicsScene."""

    def test_badge_added_to_scene(self, qtbot):
        """Badge корректно добавляется в QGraphicsScene и присутствует в items()."""
        scene = QGraphicsScene()
        badge = WireMetricsBadge()
        scene.addItem(badge)
        assert badge in scene.items()

    def test_badge_removed_from_scene(self, qtbot):
        """Badge корректно удаляется из QGraphicsScene."""
        scene = QGraphicsScene()
        badge = WireMetricsBadge()
        scene.addItem(badge)
        scene.removeItem(badge)
        assert badge not in scene.items()

    def test_multiple_badges_in_scene(self, qtbot):
        """Несколько badge-ов могут одновременно находиться в одной сцене."""
        scene = QGraphicsScene()
        badges = [WireMetricsBadge() for _ in range(3)]
        for b in badges:
            scene.addItem(b)
        items = scene.items()
        for b in badges:
            assert b in items
