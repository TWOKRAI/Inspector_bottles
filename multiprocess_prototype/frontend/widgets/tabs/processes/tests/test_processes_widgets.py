# -*- coding: utf-8 -*-
"""Тесты Фазы D (processes-workers-runtime): ProcessCard + WorkerTable (pytest-qt)."""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.processes.widgets import ProcessCard, WorkerTable


# ====================================================================== #
#  ProcessCard                                                          #
# ====================================================================== #


class TestProcessCard:
    def test_creates_with_actions(self, qtbot) -> None:
        card = ProcessCard(entity_id="camera_0", title="camera_0", category="source")
        qtbot.addWidget(card)
        assert card.entity_id == "camera_0"
        # Все 4 действия для незащищённого процесса
        assert set(card._action_buttons) == {"start", "stop", "restart", "delete"}

    def test_protected_hides_stop_and_delete(self, qtbot) -> None:
        card = ProcessCard(entity_id="gui", title="gui", category="utility", protected=True)
        qtbot.addWidget(card)
        assert "stop" not in card._action_buttons
        assert "delete" not in card._action_buttons
        assert "start" in card._action_buttons

    def test_set_status_updates_pill(self, qtbot) -> None:
        card = ProcessCard(entity_id="p", title="p")
        qtbot.addWidget(card)
        card.set_status("running")
        assert card._pill.text() == "работает"
        assert card._pill.property("status") == "running"
        assert card.property("status") == "running"

    def test_set_metric_updates_label(self, qtbot) -> None:
        card = ProcessCard(entity_id="p", title="p")
        qtbot.addWidget(card)
        card.set_metric("FPS", "30.1")
        assert "30.1" in card.metric_label("FPS").text()

    def test_action_clicked_emitted(self, qtbot) -> None:
        card = ProcessCard(entity_id="cam", title="cam")
        qtbot.addWidget(card)
        captured: list[tuple[str, str]] = []
        card.action_clicked.connect(lambda eid, aid: captured.append((eid, aid)))
        card._action_buttons["restart"].click()
        assert captured == [("cam", "restart")]


# ====================================================================== #
#  WorkerTable                                                          #
# ====================================================================== #


def _workers() -> list[dict]:
    return [
        {
            "worker_name": "message_processor",
            "priority": "NORMAL",
            "execution_mode": "loop",
            "target_interval_ms": None,
            "protected": True,
            "status": "running",
        },
        {
            "worker_name": "grabber",
            "priority": "REALTIME",
            "execution_mode": "loop",
            "target_interval_ms": 33,
            "protected": False,
            "status": "running",
        },
    ]


class TestWorkerTable:
    def test_set_workers_populates(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        table.set_workers(_workers())
        assert table.worker_names() == ["message_processor", "grabber"]

    def test_priority_combo_has_five_values(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        table.set_workers(_workers())
        combo = table._table.cellWidget(1, 1)  # grabber priority
        assert combo.count() == 5
        assert combo.currentText() == "REALTIME"

    def test_protected_row_combos_disabled(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        table.set_workers(_workers())
        priority_combo = table._table.cellWidget(0, 1)  # message_processor
        interval_spin = table._table.cellWidget(0, 3)
        assert priority_combo.isEnabled() is False
        assert interval_spin.isEnabled() is False

    def test_changed_emitted_on_priority_edit(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        table.set_workers(_workers())
        captured: list[tuple] = []
        table.changed.connect(lambda n, f, v: captured.append((n, f, v)))
        combo = table._table.cellWidget(1, 1)  # grabber
        combo.setCurrentText("BATCH")
        assert ("grabber", "priority", "BATCH") in captured

    def test_no_changed_during_populate(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        captured: list[tuple] = []
        table.changed.connect(lambda n, f, v: captured.append((n, f, v)))
        table.set_workers(_workers())
        assert captured == []  # populate не эмитит changed

    def test_protected_combo_change_does_not_emit(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        table.set_workers(_workers())
        captured: list[tuple] = []
        table.changed.connect(lambda n, f, v: captured.append((n, f, v)))
        # программно меняем защищённый combo (он disabled, но проверяем guard)
        table._emit_changed("message_processor", "priority", "BATCH")
        assert captured == []

    def test_add_requested_emitted(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        captured: list[bool] = []
        table.add_requested.connect(lambda: captured.append(True))
        table._add_btn.click()
        assert captured == [True]

    def test_remove_requested_for_selected(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        table.set_workers(_workers())
        captured: list[str] = []
        table.remove_requested.connect(lambda n: captured.append(n))
        table._table.selectRow(1)  # grabber
        table._remove_btn.click()
        assert captured == ["grabber"]

    def test_remove_disabled_for_protected_selection(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        table.set_workers(_workers())
        table._table.selectRow(0)  # message_processor (protected)
        assert table._remove_btn.isEnabled() is False

    def test_telemetry_widgets_exposed(self, qtbot) -> None:
        table = WorkerTable()
        qtbot.addWidget(table)
        table.set_workers(_workers())
        widgets = table.telemetry_widgets("grabber")
        assert "status" in widgets
        assert "hz" in widgets
