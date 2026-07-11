# -*- coding: utf-8 -*-
"""Тесты free-layout: drag меняет ТОЛЬКО позицию ноды (не процесс) + удаление плагин-ноды.

Покрытие (presenter + реальный orchestrator):
  - drag ноды (on_node_moved / scene.on_node_drag_finished) → позиция меняется,
    топология (членство плагина в процессе) НЕ меняется (free-layout Task 1);
  - смена процесса остаётся доступной через combo инспектора
    (_on_move_to_process_requested → MovePlugin);
  - remove_selected(плагин-нода) в процессе с >1 плагином → RemovePlugin (только плагин);
  - remove_selected(плагин-нода) в процессе с 1 плагином → RemoveProcess (процесс).

Refs: plans/2026-06-08_pipeline-free-layout.md (Task 1)
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services_with_orchestrator


def _plugins(topo: dict, process: str) -> list[str]:
    """Имена плагинов процесса по порядку."""
    proc = next(p for p in topo["processes"] if p["process_name"] == process)
    return [pl["plugin_name"] for pl in proc.get("plugins", [])]


def _process_names(topo: dict) -> list[str]:
    return [p["process_name"] for p in topo["processes"]]


def _chain_two_processes():
    """preproc[resize, grayscale] + detector[yolo]."""
    topo = {
        "processes": [
            {
                "process_name": "preproc",
                "plugins": [{"plugin_name": "resize"}, {"plugin_name": "grayscale"}],
            },
            {"process_name": "detector", "plugins": [{"plugin_name": "yolo"}]},
        ],
        "wires": [],
    }
    return make_pipeline_services_with_orchestrator(topology=topo)


class TestDragOnlyMoves:
    """Drag меняет позицию, но НЕ членство ноды в процессе (free-layout)."""

    def test_drag_records_position_without_topology_change(self):
        """on_node_moved пишет позицию в _gui_positions, топология не меняется."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        before = services.topology.load().to_dict()
        p.on_node_moved("preproc.grayscale", 999.0, 333.0)
        after = services.topology.load().to_dict()

        # Позиция записана
        assert p._layout.gui_positions["preproc.grayscale"] == (999.0, 333.0)
        # Членство плагинов не изменилось — drag не «объединяет под процесс»
        assert _plugins(after, "preproc") == _plugins(before, "preproc") == ["resize", "grayscale"]
        assert _plugins(after, "detector") == ["yolo"]

    def test_scene_drag_finished_emits_position_only(self, qtbot):
        """scene.on_node_drag_finished эмитит node_position_changed (без MovePlugin)."""
        scene = GraphScene()
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.node_item import NodeData

        scene.add_node(NodeData("preproc.grayscale", "grayscale", x=10, y=20, process_name="preproc", plugin_index=1))
        received: list[tuple] = []
        scene.node_position_changed.connect(lambda nid, x, y: received.append((nid, x, y)))

        node = scene.get_node("preproc.grayscale")
        node.setPos(400.0, 500.0)
        scene.on_node_drag_finished("preproc.grayscale")

        assert received == [("preproc.grayscale", 400.0, 500.0)]


class TestComboStillMovesProcess:
    """Смена процесса остаётся доступной через combo инспектора (MovePlugin)."""

    def test_move_to_process_via_combo(self):
        """_on_move_to_process_requested → MovePlugin (плагин уходит в другой процесс)."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p._on_move_to_process_requested("detector", "preproc")

        topo = services.topology.load().to_dict()
        # yolo переехал из detector в preproc; detector опустел и удалён каскадом
        assert "yolo" in _plugins(topo, "preproc")
        assert "detector" not in _process_names(topo)


class TestDeletePluginNode:
    def test_remove_one_plugin_keeps_process(self):
        """remove_selected(плагин-нода) в процессе с >1 плагином → RemovePlugin."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["preproc.grayscale"])

        topo = services.topology.load().to_dict()
        assert "preproc" in _process_names(topo)  # процесс остался
        assert _plugins(topo, "preproc") == ["resize"]  # удалён только grayscale

    def test_remove_last_plugin_removes_process(self):
        """remove_selected(плагин-нода) в процессе с 1 плагином → RemoveProcess."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["detector.yolo"])

        topo = services.topology.load().to_dict()
        assert "detector" not in _process_names(topo)  # процесс удалён целиком

    def test_remove_by_process_name_legacy(self):
        """Legacy: remove_selected(имя процесса без точки) → RemoveProcess."""
        services = _chain_two_processes()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["preproc"])

        topo = services.topology.load().to_dict()
        assert "preproc" not in _process_names(topo)
