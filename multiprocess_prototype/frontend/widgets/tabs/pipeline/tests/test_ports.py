"""Тесты для PortItem, TempWireItem и wire creation."""
from __future__ import annotations

import pytest

from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.port_item import PortItem
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.temp_wire import TempWireItem
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.node_item import NodeData, NodeItem
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_view import GraphView, InteractionMode
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.constants import NODE_WIDTH, NODE_HEIGHT


# ------------------------------------------------------------------ #
#  PortItem                                                            #
# ------------------------------------------------------------------ #

class TestPortItem:
    def test_port_item_create(self, qtbot):
        """Создание PortItem с типом и endpoint."""
        port = PortItem("output", "proc1.plugin.frame", "source")
        assert port.port_type == "output"
        assert port.endpoint == "proc1.plugin.frame"

    def test_port_is_input(self, qtbot):
        """is_input возвращает True для input порта."""
        port = PortItem("input", "proc1.input")
        assert port.is_input is True
        assert port.is_output is False

    def test_port_is_output(self, qtbot):
        """is_output возвращает True для output порта."""
        port = PortItem("output", "proc1.output")
        assert port.is_output is True
        assert port.is_input is False

    def test_port_center_scene_pos(self, qtbot):
        """Позиция порта в scene coordinates."""
        scene = GraphScene()
        node = scene.add_node(NodeData("a", "A", x=100, y=200))
        # Порт добавлен как child ноды, позиция = node.pos + port.pos
        port = node.input_port
        x, y = port.center_scene_pos()
        # Input порт на левом краю (x=0 относительно ноды), середина по высоте
        assert x == pytest.approx(100.0, abs=1)
        assert y == pytest.approx(200.0 + NODE_HEIGHT / 2, abs=1)

    def test_port_default_category(self, qtbot):
        """Порт с категорией по умолчанию (utility)."""
        port = PortItem("input", "x.input")
        assert port._category == "utility"


# ------------------------------------------------------------------ #
#  NodeItem + порты                                                    #
# ------------------------------------------------------------------ #

class TestNodePorts:
    def test_node_has_ports(self, qtbot):
        """NodeItem имеет input_port и output_port children."""
        data = NodeData("proc1", "Camera", category="source")
        scene = GraphScene()
        item = scene.add_node(data)
        assert item.input_port is not None
        assert item.output_port is not None
        assert isinstance(item.input_port, PortItem)
        assert isinstance(item.output_port, PortItem)

    def test_node_ports_positioned(self, qtbot):
        """Input порт слева, output порт справа."""
        data = NodeData("proc1", "Camera", x=50, y=50)
        scene = GraphScene()
        item = scene.add_node(data)

        # Позиции портов относительно ноды
        inp_pos = item.input_port.pos()
        out_pos = item.output_port.pos()

        # Input на x=0 (левый край), output на x=NODE_WIDTH (правый край)
        assert inp_pos.x() == pytest.approx(0.0)
        assert out_pos.x() == pytest.approx(NODE_WIDTH)

        # Оба на середине по высоте
        assert inp_pos.y() == pytest.approx(NODE_HEIGHT / 2)
        assert out_pos.y() == pytest.approx(NODE_HEIGHT / 2)

    def test_node_port_endpoints(self, qtbot):
        """Endpoint портов содержит node_id."""
        data = NodeData("camera", "Camera")
        scene = GraphScene()
        item = scene.add_node(data)
        assert "camera" in item.input_port.endpoint
        assert "camera" in item.output_port.endpoint


# ------------------------------------------------------------------ #
#  TempWireItem                                                        #
# ------------------------------------------------------------------ #

class TestTempWireItem:
    def test_temp_wire_create(self, qtbot):
        """TempWireItem создаётся с начальной позицией."""
        wire = TempWireItem((100, 200))
        assert wire._start == (100, 200)
        assert wire.zValue() == 1000

    def test_temp_wire_update_end(self, qtbot):
        """Path обновляется после update_end."""
        wire = TempWireItem((0, 0))
        assert wire.path().isEmpty()  # До обновления пуст

        wire.update_end((200, 100))
        assert not wire.path().isEmpty()


# ------------------------------------------------------------------ #
#  GraphScene.port_at                                                  #
# ------------------------------------------------------------------ #

class TestScenePortAt:
    def test_scene_port_at(self, qtbot):
        """GraphScene.port_at() находит порт по scene coordinates."""
        scene = GraphScene()
        node = scene.add_node(NodeData("a", "A", x=100, y=100))

        # Output порт расположен на (100 + NODE_WIDTH, 100 + NODE_HEIGHT/2)
        ox, oy = node.output_port.center_scene_pos()
        port = scene.port_at((ox, oy))
        assert port is not None
        assert port.is_output

    def test_scene_port_at_empty(self, qtbot):
        """port_at на пустом месте возвращает None."""
        scene = GraphScene()
        scene.add_node(NodeData("a", "A", x=100, y=100))
        # Далеко от узла
        result = scene.port_at((9999, 9999))
        assert result is None


# ------------------------------------------------------------------ #
#  GraphView — InteractionMode                                         #
# ------------------------------------------------------------------ #

class TestGraphViewInteraction:
    def test_graph_view_has_interaction_mode(self, qtbot):
        """GraphView имеет _mode = SELECT по умолчанию."""
        scene = GraphScene()
        view = GraphView(scene)
        qtbot.addWidget(view)
        assert view._mode == InteractionMode.SELECT

    def test_graph_view_has_wire_created_signal(self, qtbot):
        """GraphView имеет сигнал wire_created."""
        scene = GraphScene()
        view = GraphView(scene)
        qtbot.addWidget(view)
        assert hasattr(view, "wire_created")

    def test_graph_view_no_temp_wire_initially(self, qtbot):
        """Нет временного wire при создании."""
        scene = GraphScene()
        view = GraphView(scene)
        qtbot.addWidget(view)
        assert view._temp_wire is None
        assert view._wire_start_port is None
