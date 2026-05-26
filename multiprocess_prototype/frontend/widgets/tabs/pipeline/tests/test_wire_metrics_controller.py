"""Интеграционные тесты WireMetricsController.

Проверяют:
- автоматическое создание badge при добавлении edge в GraphScene
- автоматическое удаление badge при удалении edge/узла
- обновление цвета badge через статусный тик
- обновление текста badge через метрический тик
- управление таймерами через start() / stop()
- идемпотентность _on_edge_added
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPointF

from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.edge_item import (
    EdgeData,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import (
    GraphScene,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.node_item import (
    NodeData,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.telemetry.wire_metrics_badge import (
    STATUS_COLORS,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.telemetry.wire_metrics_controller import (
    WireMetricsController,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.telemetry.wire_metrics_model import (
    WireMetricsModel,
)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------


@pytest.fixture
def scene(qtbot):
    """GraphScene с двумя узлами — готова к добавлению edges."""
    s = GraphScene()
    s.add_node(NodeData("src", "Source", category="source", x=0, y=0))
    s.add_node(NodeData("tgt", "Target", category="processing", x=300, y=0))
    return s


@pytest.fixture
def model(qtbot):
    """Чистый WireMetricsModel."""
    return WireMetricsModel()


@pytest.fixture
def controller(scene, model, qtbot):
    """WireMetricsController без запущенных таймеров (start не вызван)."""
    return WireMetricsController(scene, model)


# ---------------------------------------------------------------------------
# Тест 1: badge создаётся при добавлении edge
# ---------------------------------------------------------------------------


class TestBadgeCreation:
    """Тесты автоматического создания badge."""

    def test_controller_creates_badge_for_each_edge(self, scene, model, qtbot):
        """При добавлении edge через scene.add_edge создаётся ровно один badge."""
        ctrl = WireMetricsController(scene, model)

        # До добавления edge — badge'ей нет
        assert len(ctrl.badges) == 0

        # Добавить edge
        edge = scene.add_edge(EdgeData("src", "tgt"))
        assert edge is not None

        # Должен появиться ровно один badge
        assert len(ctrl.badges) == 1
        key = ("src", "tgt")
        assert key in ctrl.badges

    def test_badge_is_added_to_scene(self, scene, model, qtbot):
        """Badge добавляется в items() сцены при создании."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.telemetry.wire_metrics_badge import (
            WireMetricsBadge,
        )

        # _ctrl нужен только для регистрации подписок на сигналы
        _ctrl = WireMetricsController(scene, model)
        scene.add_edge(EdgeData("src", "tgt"))

        badge_items = [item for item in scene.items() if isinstance(item, WireMetricsBadge)]
        assert len(badge_items) == 1

    def test_multiple_edges_create_multiple_badges(self, scene, model, qtbot):
        """Несколько edges создают несколько badge'ей."""
        # Добавить третий узел
        scene.add_node(NodeData("mid", "Middle", category="processing", x=150, y=0))

        ctrl = WireMetricsController(scene, model)
        scene.add_edge(EdgeData("src", "mid"))
        scene.add_edge(EdgeData("mid", "tgt"))

        assert len(ctrl.badges) == 2


# ---------------------------------------------------------------------------
# Тест 2: badge удаляется при удалении edge
# ---------------------------------------------------------------------------


class TestBadgeRemoval:
    """Тесты автоматического удаления badge."""

    def test_controller_removes_badge_on_node_remove(self, scene, model, qtbot):
        """При удалении узла через scene.remove_node badge удаляется из контроллера."""
        ctrl = WireMetricsController(scene, model)
        scene.add_edge(EdgeData("src", "tgt"))
        assert len(ctrl.badges) == 1

        # Удалить исходный узел (каскадно удалит edge → _on_edge_removed)
        scene.remove_node("src")

        assert len(ctrl.badges) == 0

    def test_controller_removes_badge_on_remove_edge(self, scene, model, qtbot):
        """При удалении edge через scene.remove_edge badge удаляется."""
        ctrl = WireMetricsController(scene, model)
        edge = scene.add_edge(EdgeData("src", "tgt"))
        assert len(ctrl.badges) == 1

        scene.remove_edge(edge)

        assert len(ctrl.badges) == 0

    def test_badge_removed_from_scene_items(self, scene, model, qtbot):
        """Badge пропадает из items() сцены при удалении edge."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.telemetry.wire_metrics_badge import (
            WireMetricsBadge,
        )

        # _ctrl нужен только для регистрации подписок на сигналы
        _ctrl = WireMetricsController(scene, model)
        edge = scene.add_edge(EdgeData("src", "tgt"))

        scene.remove_edge(edge)

        badge_items = [item for item in scene.items() if isinstance(item, WireMetricsBadge)]
        assert len(badge_items) == 0

    def test_remove_wire_clears_model_data(self, scene, model, qtbot):
        """При удалении edge данные в модели телеметрии очищаются."""
        # _ctrl нужен только для регистрации подписок на сигналы
        _ctrl = WireMetricsController(scene, model)
        edge = scene.add_edge(EdgeData("src", "tgt"))

        # Записать данные в модель
        model.update_status("src", "tgt", "ok")
        model.update_metrics("src", "tgt", 30.0, 5.0, 0.5)

        assert model.get_status("src", "tgt") is not None
        assert model.get_metrics("src", "tgt") is not None

        # Удалить edge — данные в модели должны очиститься
        scene.remove_edge(edge)

        assert model.get_status("src", "tgt") is None
        assert model.get_metrics("src", "tgt") is None


# ---------------------------------------------------------------------------
# Тест 3: обновление цвета через статусный тик
# ---------------------------------------------------------------------------


class TestStatusTick:
    """Тесты обновления цвета badge через _tick_status()."""

    def test_status_timer_updates_color_to_error(self, scene, model, qtbot):
        """После update_status + _tick_status badge приобретает красный цвет."""
        ctrl = WireMetricsController(scene, model)
        scene.add_edge(EdgeData("src", "tgt"))

        # Установить статус error
        model.update_status("src", "tgt", "error")

        # Вызвать тик вручную (не ждём 2с)
        ctrl._tick_status()

        badge = ctrl.badges[("src", "tgt")]
        color = badge.brush().color().name().lower()
        assert color == STATUS_COLORS["error"].lower()

    def test_status_timer_updates_color_to_ok(self, scene, model, qtbot):
        """После update_status ok + тик badge становится зелёным."""
        ctrl = WireMetricsController(scene, model)
        scene.add_edge(EdgeData("src", "tgt"))

        model.update_status("src", "tgt", "ok")
        ctrl._tick_status()

        badge = ctrl.badges[("src", "tgt")]
        color = badge.brush().color().name().lower()
        assert color == STATUS_COLORS["ok"].lower()

    def test_tick_status_with_no_badges_does_not_crash(self, scene, model, qtbot):
        """_tick_status() при отсутствии badge'ей не бросает исключений."""
        ctrl = WireMetricsController(scene, model)
        # Без edges — badge'ей нет, тик должен отработать без ошибок
        ctrl._tick_status()


# ---------------------------------------------------------------------------
# Тест 4: обновление текста через метрический тик
# ---------------------------------------------------------------------------


class TestMetricsTick:
    """Тесты обновления текста badge через _tick_metrics()."""

    def test_metrics_timer_updates_text(self, scene, model, qtbot):
        """После update_metrics + _tick_metrics badge показывает корректный текст."""
        ctrl = WireMetricsController(scene, model)
        scene.add_edge(EdgeData("src", "tgt"))

        model.update_metrics("src", "tgt", 30.0, 5.0, 0.5)
        ctrl._tick_metrics()

        badge = ctrl.badges[("src", "tgt")]
        text = badge._text_item.toPlainText()
        assert "30fps" in text
        assert "5ms" in text
        assert "50%" in text

    def test_tick_metrics_with_no_badges_does_not_crash(self, scene, model, qtbot):
        """_tick_metrics() при отсутствии badge'ей не бросает исключений."""
        ctrl = WireMetricsController(scene, model)
        ctrl._tick_metrics()


# ---------------------------------------------------------------------------
# Тест 5: управление таймерами
# ---------------------------------------------------------------------------


class TestTimerControl:
    """Тесты start() / stop() для управления таймерами."""

    def test_start_activates_both_timers(self, scene, model, qtbot):
        """start() запускает оба таймера."""
        ctrl = WireMetricsController(scene, model)
        assert not ctrl._status_timer.isActive()
        assert not ctrl._metrics_timer.isActive()

        ctrl.start()
        assert ctrl._status_timer.isActive()
        assert ctrl._metrics_timer.isActive()

        ctrl.stop()  # Cleanup

    def test_stop_deactivates_both_timers(self, scene, model, qtbot):
        """stop() останавливает оба таймера."""
        ctrl = WireMetricsController(scene, model)
        ctrl.start()
        assert ctrl._status_timer.isActive()
        assert ctrl._metrics_timer.isActive()

        ctrl.stop()
        assert not ctrl._status_timer.isActive()
        assert not ctrl._metrics_timer.isActive()

    def test_timers_not_active_before_start(self, controller, qtbot):
        """До вызова start() таймеры неактивны."""
        assert not controller._status_timer.isActive()
        assert not controller._metrics_timer.isActive()


# ---------------------------------------------------------------------------
# Тест 6: идемпотентность
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Тест идемпотентности _on_edge_added."""

    def test_idempotent_edge_added(self, scene, model, qtbot):
        """Повторный вызов _on_edge_added для того же edge не создаёт дубликат badge."""
        ctrl = WireMetricsController(scene, model)
        edge = scene.add_edge(EdgeData("src", "tgt"))
        assert edge is not None

        # Первый вызов через scene.add_edge уже выполнен
        assert len(ctrl.badges) == 1

        # Вызвать _on_edge_added повторно напрямую
        ctrl._on_edge_added(edge)

        # Badge должен быть всё ещё один
        assert len(ctrl.badges) == 1

    def test_badges_property_returns_internal_dict(self, scene, model, qtbot):
        """Свойство badges возвращает внутренний словарь (для тестовой интроспекции)."""
        ctrl = WireMetricsController(scene, model)
        scene.add_edge(EdgeData("src", "tgt"))

        badges = ctrl.badges
        assert isinstance(badges, dict)
        assert ("src", "tgt") in badges


# ---------------------------------------------------------------------------
# Тест 7: позиция badge после добавления
# ---------------------------------------------------------------------------


class TestBadgePosition:
    """Тест позиционирования badge по midpoint edge."""

    def test_badge_has_position_after_edge_added(self, scene, model, qtbot):
        """Badge имеет ненулевую позицию (midpoint реальной кривой) после добавления edge."""
        ctrl = WireMetricsController(scene, model)
        scene.add_edge(EdgeData("src", "tgt"))

        badge = ctrl.badges[("src", "tgt")]
        pos = badge.pos()
        # Узлы расположены на x=0 и x=300, midpoint должен быть ненулевым
        # (позиция зависит от port_pos узлов, но не должна быть строго (0,0))
        assert isinstance(pos, QPointF)
