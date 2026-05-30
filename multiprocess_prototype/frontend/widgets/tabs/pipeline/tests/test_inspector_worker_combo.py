# -*- coding: utf-8 -*-
"""Тесты воркер-combo в NodeInspectorPanel (запрос: воркеры рядом с выбором процесса).

Воркер-combo на одной строке с combo переноса процесса; список — воркеры процесса
из топологии (+ синтетический message_processor); выбор персистится через
field_changed("assigned_worker", ...).
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector import NodeInspectorPanel

from ._helpers import make_pipeline_services

_TOPO = {
    "processes": [
        {
            "process_name": "capture_proc",
            "plugins": [{"plugin_name": "blur"}],
            "workers": [
                {"worker_name": "grabber", "priority": "REALTIME", "target_interval_ms": 33},
            ],
        },
    ],
    "wires": [],
}


def _show(panel: NodeInspectorPanel, params: dict | None = None) -> None:
    panel.show_plugin_node(
        node_id="capture_proc.blur",
        category="processing",
        process_name="capture_proc",
        plugin_name="blur",
        plugins=[{"plugin_name": "blur"}],
        params=params or {},
    )


def test_worker_combo_populated_from_topology(qtbot) -> None:
    panel = NodeInspectorPanel()
    qtbot.addWidget(panel)
    panel.set_services(make_pipeline_services(topology=_TOPO))
    _show(panel)
    combo = panel._move_worker_combo
    names = [combo.itemText(i) for i in range(combo.count())]
    assert "message_processor" in names  # синтетический системный воркер
    assert "grabber" in names  # воркер процесса из топологии


def test_worker_row_visible_in_plugin_mode(qtbot) -> None:
    panel = NodeInspectorPanel()
    qtbot.addWidget(panel)
    panel.set_services(make_pipeline_services(topology=_TOPO))
    _show(panel)
    # Строка «Процесс / Воркер» видима в plugin-режиме (независимо от наличия др. процессов)
    assert panel._move_process_form.isVisible() or panel._move_process_form.isVisibleTo(panel)
    assert panel._move_worker_combo.count() >= 1


def test_worker_selection_emits_field_changed(qtbot) -> None:
    panel = NodeInspectorPanel()
    qtbot.addWidget(panel)
    panel.set_services(make_pipeline_services(topology=_TOPO))
    _show(panel)
    captured: list[tuple] = []
    panel.field_changed.connect(lambda p, f, v: captured.append((p, f, v)))
    combo = panel._move_worker_combo
    idx = combo.findData("grabber")
    assert idx >= 0
    combo.setCurrentIndex(idx)
    assert ("capture_proc", "assigned_worker", "grabber") in captured


def test_worker_combo_preselects_assigned_worker(qtbot) -> None:
    panel = NodeInspectorPanel()
    qtbot.addWidget(panel)
    panel.set_services(make_pipeline_services(topology=_TOPO))
    _show(panel, params={"assigned_worker": "grabber"})
    combo = panel._move_worker_combo
    assert combo.currentData() == "grabber"


def test_no_emit_during_populate(qtbot) -> None:
    panel = NodeInspectorPanel()
    qtbot.addWidget(panel)
    panel.set_services(make_pipeline_services(topology=_TOPO))
    captured: list[tuple] = []
    panel.field_changed.connect(lambda p, f, v: captured.append((p, f, v)))
    _show(panel, params={"assigned_worker": "grabber"})
    # Заполнение/preselect не должно эмитить field_changed
    assert all(f != "assigned_worker" for _p, f, _v in captured)
