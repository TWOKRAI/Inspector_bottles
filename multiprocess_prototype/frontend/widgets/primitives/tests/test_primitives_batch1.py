"""Тесты для примитивов batch 1: StatusIndicator, EntityCard, ActionToolbar."""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from multiprocess_prototype.frontend.widgets.primitives import (
    ActionToolbar,
    CardAction,
    EntityCard,
    StatusIndicator,
)


# ------------------------------------------------------------------ #
#  StatusIndicator                                                     #
# ------------------------------------------------------------------ #


class TestStatusIndicator:
    """Тесты StatusIndicator."""

    def test_default_state(self, qtbot):
        w = StatusIndicator()
        qtbot.addWidget(w)
        assert w.state() == "unknown"

    def test_set_state(self, qtbot):
        w = StatusIndicator()
        qtbot.addWidget(w)
        w.set_state("running")
        assert w.state() == "running"

    def test_unknown_state_fallback(self, qtbot):
        w = StatusIndicator()
        qtbot.addWidget(w)
        w.set_state("nonexistent_state")
        assert w.state() == "nonexistent_state"
        # Не должно упасть — используется цвет "unknown"

    def test_custom_color_map(self, qtbot):
        w = StatusIndicator(color_map={"active": "#00ff00"})
        qtbot.addWidget(w)
        w.set_state("active")
        assert w.state() == "active"

    def test_size_hint(self, qtbot):
        w = StatusIndicator(size=16)
        qtbot.addWidget(w)
        assert w.sizeHint().width() == 16
        assert w.sizeHint().height() == 16

    def test_minimum_size_hint(self, qtbot):
        w = StatusIndicator(size=20)
        qtbot.addWidget(w)
        assert w.minimumSizeHint().width() == 20

    def test_paint_does_not_crash(self, qtbot):
        """paintEvent не должен падать при любых состояниях."""
        w = StatusIndicator()
        qtbot.addWidget(w)
        for state in ("running", "stopped", "error", "starting", "ready", "unknown", "???"):
            w.set_state(state)
            w.repaint()


# ------------------------------------------------------------------ #
#  EntityCard                                                          #
# ------------------------------------------------------------------ #


class TestEntityCard:
    """Тесты EntityCard."""

    def test_create_minimal(self, qtbot):
        card = EntityCard("proc1", "Camera Process")
        qtbot.addWidget(card)
        assert card.entity_id == "proc1"

    def test_create_with_actions(self, qtbot):
        actions = [CardAction("start", "Start"), CardAction("stop", "Stop")]
        card = EntityCard("proc1", "Test", actions=actions)
        qtbot.addWidget(card)
        assert "start" in card._action_buttons
        assert "stop" in card._action_buttons

    def test_set_status(self, qtbot):
        card = EntityCard("proc1", "Test")
        qtbot.addWidget(card)
        card.set_status("running")
        assert card._indicator.state() == "running"

    def test_set_title(self, qtbot):
        card = EntityCard("proc1", "Original")
        qtbot.addWidget(card)
        card.set_title("Updated")
        assert card._title_label.text() == "Updated"

    def test_set_metrics_new_keys(self, qtbot):
        card = EntityCard("proc1", "Test")
        qtbot.addWidget(card)
        card.set_metrics({"FPS": "25", "PID": "1234"})
        assert "FPS" in card._metric_labels
        assert card._metric_labels["FPS"].text() == "25"
        assert card._metric_labels["PID"].text() == "1234"

    def test_set_metrics_update_existing(self, qtbot):
        card = EntityCard("proc1", "Test")
        qtbot.addWidget(card)
        card.set_metrics({"FPS": "25"})
        card.set_metrics({"FPS": "30"})
        assert card._metric_labels["FPS"].text() == "30"
        # Не должно дублироваться
        assert card._metrics_layout.rowCount() == 1

    def test_action_signal(self, qtbot):
        actions = [CardAction("start", "Start")]
        card = EntityCard("proc1", "Test", actions=actions)
        qtbot.addWidget(card)

        with qtbot.waitSignal(card.action_clicked) as blocker:
            card._action_buttons["start"].click()
        assert blocker.args == ["proc1", "start"]

    def test_set_action_enabled(self, qtbot):
        actions = [CardAction("start", "Start")]
        card = EntityCard("proc1", "Test", actions=actions)
        qtbot.addWidget(card)
        card.set_action_enabled("start", False)
        assert not card._action_buttons["start"].isEnabled()

    def test_set_action_enabled_unknown(self, qtbot):
        """set_action_enabled с несуществующим action_id не падает."""
        card = EntityCard("proc1", "Test")
        qtbot.addWidget(card)
        card.set_action_enabled("nonexistent", False)  # не должно упасть


# ------------------------------------------------------------------ #
#  ActionToolbar                                                       #
# ------------------------------------------------------------------ #


class TestActionToolbar:
    """Тесты ActionToolbar."""

    def test_create_empty(self, qtbot):
        tb = ActionToolbar()
        qtbot.addWidget(tb)
        assert len(tb._buttons) == 0

    def test_create_with_actions(self, qtbot):
        tb = ActionToolbar(actions=[("start", "Start"), ("stop", "Stop")])
        qtbot.addWidget(tb)
        assert len(tb._buttons) == 2

    def test_add_action(self, qtbot):
        tb = ActionToolbar()
        qtbot.addWidget(tb)
        btn = tb.add_action("test", "Test Button")
        assert btn is not None
        assert "test" in tb._buttons

    def test_set_enabled(self, qtbot):
        tb = ActionToolbar(actions=[("start", "Start")])
        qtbot.addWidget(tb)
        tb.set_enabled("start", False)
        assert not tb._buttons["start"].isEnabled()
        tb.set_enabled("start", True)
        assert tb._buttons["start"].isEnabled()

    def test_set_enabled_unknown(self, qtbot):
        """set_enabled с несуществующим action_id не падает."""
        tb = ActionToolbar()
        qtbot.addWidget(tb)
        tb.set_enabled("nonexistent", False)

    def test_signal(self, qtbot):
        tb = ActionToolbar(actions=[("start", "Start")])
        qtbot.addWidget(tb)
        with qtbot.waitSignal(tb.action_triggered) as blocker:
            tb._buttons["start"].click()
        assert blocker.args == ["start"]

    def test_add_stretch(self, qtbot):
        tb = ActionToolbar()
        qtbot.addWidget(tb)
        tb.add_action("a", "A")
        tb.add_stretch()
        tb.add_action("b", "B")
        # Не должно упасть

    def test_add_separator(self, qtbot):
        tb = ActionToolbar()
        qtbot.addWidget(tb)
        tb.add_action("a", "A")
        tb.add_separator()
        tb.add_action("b", "B")
        # Не должно упасть
