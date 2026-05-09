"""Тесты для Pipeline Tab -- сцена, узлы, связи."""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest

from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.node_item import NodeData, NodeItem
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.edge_item import EdgeData, EdgeItem
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_view import GraphView
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.tab import PipelineTab
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter


class TestNodeItem:
    def test_create(self, qtbot):
        data = NodeData("proc1", "Camera", "source", "source", 100, 200)
        scene = GraphScene()
        item = NodeItem(data)
        scene.addItem(item)
        assert item.node_id == "proc1"
        assert item.pos().x() == 100

    def test_ports(self, qtbot):
        data = NodeData("proc1", "Test", category="processing")
        item = NodeItem(data)
        ox, oy = item.output_port_pos()
        ix, iy = item.input_port_pos()
        assert ox > ix  # output правее input


class TestEdgeItem:
    def test_create(self, qtbot):
        data = EdgeData("a", "b")
        edge = EdgeItem(data)
        assert edge.source_id == "a"
        assert edge.target_id == "b"

    def test_update_path(self, qtbot):
        data = EdgeData("a", "b")
        edge = EdgeItem(data)
        edge.update_path((0, 50), (200, 50))
        # Path не должен быть пустым
        assert not edge.path().isEmpty()


class TestGraphScene:
    def test_add_node(self, qtbot):
        scene = GraphScene()
        node = scene.add_node(NodeData("a", "Node A"))
        assert scene.node_count() == 1
        assert scene.get_node("a") is node

    def test_remove_node(self, qtbot):
        scene = GraphScene()
        scene.add_node(NodeData("a", "A"))
        scene.add_node(NodeData("b", "B"))
        scene.add_edge(EdgeData("a", "b"))

        scene.remove_node("a")
        assert scene.node_count() == 1
        assert scene.edge_count() == 0  # каскадное удаление

    def test_add_edge(self, qtbot):
        scene = GraphScene()
        scene.add_node(NodeData("a", "A"))
        scene.add_node(NodeData("b", "B"))
        edge = scene.add_edge(EdgeData("a", "b"))
        assert edge is not None
        assert scene.edge_count() == 1

    def test_add_edge_missing_node(self, qtbot):
        scene = GraphScene()
        scene.add_node(NodeData("a", "A"))
        edge = scene.add_edge(EdgeData("a", "nonexistent"))
        assert edge is None

    def test_load_from_data(self, qtbot):
        scene = GraphScene()
        nodes = [
            NodeData("a", "A", category="source"),
            NodeData("b", "B", category="processing"),
            NodeData("c", "C", category="output"),
        ]
        edges = [EdgeData("a", "b"), EdgeData("b", "c")]
        scene.load_from_data(nodes, edges)
        assert scene.node_count() == 3
        assert scene.edge_count() == 2

    def test_export_data(self, qtbot):
        scene = GraphScene()
        scene.add_node(NodeData("a", "A", x=10, y=20))
        scene.add_node(NodeData("b", "B", x=30, y=40))
        scene.add_edge(EdgeData("a", "b"))

        nodes, edges = scene.export_data()
        assert len(nodes) == 2
        assert len(edges) == 1

    def test_clear_all(self, qtbot):
        scene = GraphScene()
        scene.add_node(NodeData("a", "A"))
        scene.clear_all()
        assert scene.node_count() == 0

    def test_remove_edge(self, qtbot):
        scene = GraphScene()
        scene.add_node(NodeData("a", "A"))
        scene.add_node(NodeData("b", "B"))
        edge = scene.add_edge(EdgeData("a", "b"))
        scene.remove_edge(edge)
        assert scene.edge_count() == 0


    def test_edge_updates_on_node_move(self, qtbot):
        """Edge'ы обновляются при перемещении узла."""
        scene = GraphScene()
        scene.add_node(NodeData("a", "A", x=0, y=0))
        scene.add_node(NodeData("b", "B", x=200, y=0))
        edge = scene.add_edge(EdgeData("a", "b"))

        # Запомнить path до перемещения
        path_before = edge.path().boundingRect()

        # Переместить узел "a" — itemChange вызовет on_node_moved
        node_a = scene.get_node("a")
        node_a.setPos(100, 100)

        # Path должен измениться
        path_after = edge.path().boundingRect()
        assert path_before != path_after


class TestGraphView:
    def test_create(self, qtbot):
        scene = GraphScene()
        view = GraphView(scene)
        qtbot.addWidget(view)

    def test_zoom_in(self, qtbot):
        scene = GraphScene()
        view = GraphView(scene)
        qtbot.addWidget(view)
        old_zoom = view._current_zoom
        view.zoom_in()
        assert view._current_zoom > old_zoom

    def test_zoom_out(self, qtbot):
        scene = GraphScene()
        view = GraphView(scene)
        qtbot.addWidget(view)
        old_zoom = view._current_zoom
        view.zoom_out()
        assert view._current_zoom < old_zoom


def _make_mock_ctx(topology=None):
    ctx = MagicMock()
    ctx.config = {
        "topology": topology or {
            "processes": [
                {"process_name": "camera", "plugins": [{"plugin_name": "capture"}]},
                {"process_name": "processor", "plugins": [{"plugin_name": "color_mask"}]},
            ],
            "wires": [
                {"source": "camera.capture.frame", "target": "processor.color_mask.frame"},
            ],
        },
    }
    ctx.extras = {}
    ctx.plugin_registry.return_value = None
    ctx.bindings.return_value = None
    return ctx


class TestPipelinePresenter:
    def test_load_from_config(self):
        ctx = _make_mock_ctx()
        p = PipelinePresenter(ctx)
        nodes, edges = p.load_topology_from_config()
        assert len(nodes) == 2
        assert len(edges) == 1

    def test_empty_topology(self):
        ctx = _make_mock_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
        nodes, edges = p.load_topology_from_config()
        assert len(nodes) == 0
        assert len(edges) == 0


class TestPipelineTab:
    def test_create(self, qtbot):
        ctx = _make_mock_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_scene_populated(self, qtbot):
        ctx = _make_mock_ctx()
        tab = PipelineTab(ctx)
        qtbot.addWidget(tab)
        assert tab._scene.node_count() == 2
        assert tab._scene.edge_count() == 1

    def test_toolbar_zoom(self, qtbot):
        ctx = _make_mock_ctx()
        tab = PipelineTab(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("zoom_in")
        tab._on_toolbar_action("zoom_out")
        tab._on_toolbar_action("fit")

    def test_empty_topology(self, qtbot):
        ctx = _make_mock_ctx(topology={"processes": [], "wires": []})
        tab = PipelineTab(ctx)
        qtbot.addWidget(tab)
        assert tab._scene.node_count() == 0
