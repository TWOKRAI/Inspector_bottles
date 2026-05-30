# -*- coding: utf-8 -*-
"""Тесты D.1: процесс = рамка-контейнер, плагины = отдельные ноды внутри.

Покрытие:
  - процесс с N плагинами → N плагин-нод (node_id=`{proc}.{plugin}`) + 1 контейнер;
  - неявные стрелки цепочки (implicit) между соседними плагинами;
  - внешние wires мапятся на конкретные плагин-ноды (не схлопываются до процесса);
  - контейнер обнимает свои плагин-ноды (геометрия);
  - get_node(process_name) → первая плагин-нода процесса (fallback);
  - одиночный плагин → контейнер есть, implicit-стрелок нет.

Refs: plans/pipeline-process-container-nodes.md (Phase D.1)
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services


_MULTI_TOPOLOGY = {
    "processes": [
        {
            "process_name": "preproc",
            "plugins": [{"plugin_name": "resize"}, {"plugin_name": "grayscale"}],
        },
        {"process_name": "detector", "plugins": [{"plugin_name": "yolo"}]},
    ],
    "wires": [
        {"source": "preproc.grayscale.out", "target": "detector.yolo.frame"},
    ],
}


def _render(topology: dict, qtbot) -> tuple[PipelinePresenter, GraphScene]:
    """Построить presenter + scene и отрисовать topology."""
    services = make_pipeline_services(topology=topology)
    p = PipelinePresenter(services)
    scene = GraphScene()
    p.set_scene(scene)
    nodes, edges = p.load_topology_from_config()
    p.load_scene_with_ports(nodes, edges)
    return p, scene


class TestPluginNodesAndContainers:
    def test_each_plugin_is_separate_node(self, qtbot):
        """Процесс с 2 плагинами → 2 плагин-ноды; одиночный → 1 (всего 3)."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        assert scene.node_count() == 3
        assert scene.get_node("preproc.resize") is not None
        assert scene.get_node("preproc.grayscale") is not None
        assert scene.get_node("detector.yolo") is not None

    def test_node_ids_carry_process_and_index(self, qtbot):
        """node_id = `{proc}.{plugin}`, NodeData несёт process_name/plugin_index."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        resize = scene.get_node("preproc.resize")
        grayscale = scene.get_node("preproc.grayscale")
        assert resize.process_name == "preproc"
        assert resize.plugin_index == 0
        assert grayscale.process_name == "preproc"
        assert grayscale.plugin_index == 1

    def test_container_per_process(self, qtbot):
        """На каждый процесс с плагинами — одна рамка-контейнер."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        assert scene.get_container("preproc") is not None
        assert scene.get_container("detector") is not None

    def test_container_not_counted_as_node(self, qtbot):
        """Контейнер живёт в отдельном реестре — не инфлирует node_count."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        # 3 плагин-ноды, контейнеры не считаются
        assert scene.node_count() == 3

    def test_container_encloses_its_members(self, qtbot):
        """Рамка контейнера геометрически обнимает свои плагин-ноды."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        cont = scene.get_container("preproc")
        # scene-rect контейнера в координатах сцены
        cont_rect = cont.sceneBoundingRect()
        for node_id in ("preproc.resize", "preproc.grayscale"):
            node = scene.get_node(node_id)
            assert cont_rect.contains(node.sceneBoundingRect().center()), f"Контейнер не обнимает {node_id}"


class TestImplicitChainEdges:
    def test_implicit_edge_between_consecutive_plugins(self, qtbot):
        """Между соседними плагинами процесса — неявная стрелка цепочки."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        implicit = [e for e in scene._edges if e.implicit]
        assert len(implicit) == 1
        edge = implicit[0]
        assert edge.source_id == "preproc.resize"
        assert edge.target_id == "preproc.grayscale"

    def test_single_plugin_no_implicit_edge(self, qtbot):
        """Одиночный плагин в процессе → implicit-стрелок нет."""
        topo = {
            "processes": [{"process_name": "solo", "plugins": [{"plugin_name": "blur"}]}],
            "wires": [],
        }
        _p, scene = _render(topo, qtbot)
        assert scene.get_container("solo") is not None
        assert [e for e in scene._edges if e.implicit] == []

    def test_implicit_edges_not_exported(self, qtbot):
        """export_data не возвращает implicit-стрелки (не часть domain-топологии)."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        _nodes, edges = scene.export_data()
        assert all(not e.implicit for e in edges)


class TestExternalWiresOnPluginNodes:
    def test_external_wire_connects_plugin_nodes(self, qtbot):
        """Внешний wire `preproc.grayscale.* → detector.yolo.*` соединяет плагин-ноды."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        external = [e for e in scene._edges if not e.implicit]
        assert len(external) == 1
        edge = external[0]
        assert edge.source_id == "preproc.grayscale"
        assert edge.target_id == "detector.yolo"


class TestProcessNameFallback:
    def test_get_node_by_process_returns_first_plugin(self, qtbot):
        """get_node(process_name) → первая плагин-нода процесса (fallback)."""
        _p, scene = _render(_MULTI_TOPOLOGY, qtbot)
        first = scene.get_node("preproc")
        assert first is scene.get_node("preproc.resize")

    def test_empty_process_renders_fallback_node(self, qtbot):
        """Процесс без плагинов → одна process-fallback нода (node_id=process)."""
        topo = {"processes": [{"process_name": "empty", "plugins": []}], "wires": []}
        _p, scene = _render(topo, qtbot)
        assert scene.node_count() == 1
        node = scene.get_node("empty")
        assert node is not None
        assert node.node_id == "empty"
