# -*- coding: utf-8 -*-
"""Тесты D.2: инспектор по КОНКРЕТНОМУ плагину (не plugins[0]).

Покрытие:
  - выбор плагин-ноды → inspector.current_plugin_index/process соответствуют ей;
  - field-edit маршрутизируется в SetPluginConfig с правильным plugin_index
    (config именно выбранного плагина, соседний не тронут).

Refs: plans/pipeline-process-container-nodes.md (Phase D.2)
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.inspector_panel import (
    NodeInspectorPanel,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from multiprocess_prototype.frontend.widgets.tabs.pipeline.tab import PipelineTab

from ._helpers import make_pipeline_services_with_orchestrator


def _chain_services():
    """orchestrator-сервисы: процесс preproc с цепочкой resize→grayscale."""
    topo = {
        "processes": [
            {
                "process_name": "preproc",
                "plugins": [
                    {"plugin_name": "resize", "config": {"k": 1}},
                    {"plugin_name": "grayscale", "config": {"k": 2}},
                ],
            }
        ],
        "wires": [],
    }
    return make_pipeline_services_with_orchestrator(topology=topo)


class TestSelectPluginNode:
    def test_selecting_second_plugin_sets_index(self, qtbot):
        """Выбор 2-й плагин-ноды → inspector знает process + plugin_index=1."""
        services = _chain_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)

        node = tab._scene.get_node("preproc.grayscale")
        assert node is not None
        tab._scene.clearSelection()
        node.setSelected(True)

        assert tab._inspector.current_process == "preproc"
        assert tab._inspector.current_plugin_index == 1

    def test_selecting_first_plugin_sets_index_zero(self, qtbot):
        """Выбор 1-й плагин-ноды → plugin_index=0."""
        services = _chain_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)

        node = tab._scene.get_node("preproc.resize")
        tab._scene.clearSelection()
        node.setSelected(True)

        assert tab._inspector.current_process == "preproc"
        assert tab._inspector.current_plugin_index == 0


class TestFieldEditRoutesToSelectedPlugin:
    def test_edit_second_plugin_config(self, qtbot):
        """field-edit выбранного 2-го плагина → SetPluginConfig(plugin_index=1)."""
        services = _chain_services()
        presenter = PipelinePresenter(services)
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        # Эмулируем выбор 2-го плагина (как сделал бы _on_selection_changed).
        panel.show_plugin_node(
            "preproc.grayscale",
            category="utility",
            plugin_name="grayscale",
            params={"k": 2},
            process_name="preproc",
            plugin_index=1,
        )
        panel.field_changed.emit("preproc", "k", 99)

        topo = services.topology.load().to_dict()
        proc = next(p for p in topo["processes"] if p["process_name"] == "preproc")
        assert proc["plugins"][1]["config"]["k"] == 99  # выбранный плагин обновлён
        assert proc["plugins"][0]["config"]["k"] == 1  # соседний не тронут

    def test_edit_first_plugin_config(self, qtbot):
        """field-edit 1-го плагина → SetPluginConfig(plugin_index=0)."""
        services = _chain_services()
        presenter = PipelinePresenter(services)
        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        panel.show_plugin_node(
            "preproc.resize",
            category="utility",
            plugin_name="resize",
            params={"k": 1},
            process_name="preproc",
            plugin_index=0,
        )
        panel.field_changed.emit("preproc", "k", 77)

        topo = services.topology.load().to_dict()
        proc = next(p for p in topo["processes"] if p["process_name"] == "preproc")
        assert proc["plugins"][0]["config"]["k"] == 77
        assert proc["plugins"][1]["config"]["k"] == 2
