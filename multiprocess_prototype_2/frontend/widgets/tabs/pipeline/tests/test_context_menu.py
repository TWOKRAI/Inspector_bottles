"""Тесты контекстных меню GraphScene."""
import pytest
from unittest.mock import MagicMock, patch

from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.node_item import NodeData
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.edge_item import EdgeData
from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene


class TestContextMenuSignals:
    def test_scene_has_context_signals(self, qtbot):
        """GraphScene имеет сигналы для context menu."""
        scene = GraphScene()
        assert hasattr(scene, "node_delete_requested")
        assert hasattr(scene, "node_inspect_requested")
        assert hasattr(scene, "edge_delete_requested")
        assert hasattr(scene, "add_process_requested")

    def test_node_delete_signal_emittable(self, qtbot):
        """node_delete_requested эмитится с node_id."""
        scene = GraphScene()
        received = []
        scene.node_delete_requested.connect(lambda nid: received.append(nid))
        scene.node_delete_requested.emit("test_node")
        assert received == ["test_node"]

    def test_edge_delete_signal_emittable(self, qtbot):
        """edge_delete_requested эмитится."""
        scene = GraphScene()
        received = []
        scene.edge_delete_requested.connect(lambda e: received.append(e))
        scene.edge_delete_requested.emit(MagicMock())
        assert len(received) == 1

    def test_add_process_signal_emittable(self, qtbot):
        """add_process_requested эмитится с координатами."""
        scene = GraphScene()
        received = []
        scene.add_process_requested.connect(lambda x, y: received.append((x, y)))
        scene.add_process_requested.emit(100.0, 200.0)
        assert received == [(100.0, 200.0)]

    def test_inspect_signal_emittable(self, qtbot):
        """node_inspect_requested эмитится."""
        scene = GraphScene()
        received = []
        scene.node_inspect_requested.connect(lambda nid: received.append(nid))
        scene.node_inspect_requested.emit("proc1")
        assert received == ["proc1"]


class TestContextMenuMethods:
    def test_show_node_menu_delete(self, qtbot):
        """_show_node_menu эмитит node_delete_requested при выборе Delete."""
        scene = GraphScene()
        received = []
        scene.node_delete_requested.connect(lambda nid: received.append(nid))

        node = scene.add_node(NodeData("n1", "Camera"))
        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        # Симулируем выбор Delete: exec возвращает delete_action
        with patch("multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
            mock_menu = MockMenu.return_value
            delete_action = MagicMock()
            inspect_action = MagicMock()
            mock_menu.addAction.side_effect = [inspect_action, delete_action]
            mock_menu.exec.return_value = delete_action

            scene._show_node_menu(mock_event, node)

        assert received == ["n1"]

    def test_show_node_menu_inspect(self, qtbot):
        """_show_node_menu эмитит node_inspect_requested при выборе Inspect."""
        scene = GraphScene()
        received = []
        scene.node_inspect_requested.connect(lambda nid: received.append(nid))

        node = scene.add_node(NodeData("n2", "Processor"))
        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        with patch("multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
            mock_menu = MockMenu.return_value
            inspect_action = MagicMock()
            delete_action = MagicMock()
            mock_menu.addAction.side_effect = [inspect_action, delete_action]
            mock_menu.exec.return_value = inspect_action

            scene._show_node_menu(mock_event, node)

        assert received == ["n2"]

    def test_show_edge_menu_delete(self, qtbot):
        """_show_edge_menu эмитит edge_delete_requested при выборе Delete."""
        scene = GraphScene()
        scene.add_node(NodeData("a", "A"))
        scene.add_node(NodeData("b", "B"))
        edge = scene.add_edge(EdgeData("a", "b"))

        received = []
        scene.edge_delete_requested.connect(lambda e: received.append(e))

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        with patch("multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
            mock_menu = MockMenu.return_value
            delete_action = MagicMock()
            mock_menu.addAction.return_value = delete_action
            mock_menu.exec.return_value = delete_action

            scene._show_edge_menu(mock_event, edge)

        assert len(received) == 1
        assert received[0] is edge

    def test_show_background_menu_add_process(self, qtbot):
        """_show_background_menu эмитит add_process_requested при выборе Add Process."""
        from PySide6.QtCore import QPointF
        scene = GraphScene()
        received = []
        scene.add_process_requested.connect(lambda x, y: received.append((x, y)))

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        pos = QPointF(150.0, 250.0)

        with patch("multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
            mock_menu = MockMenu.return_value
            add_action = MagicMock()
            mock_menu.addAction.return_value = add_action
            mock_menu.exec.return_value = add_action

            scene._show_background_menu(mock_event, pos)

        assert received == [(150.0, 250.0)]

    def test_show_background_menu_cancel(self, qtbot):
        """_show_background_menu не эмитит сигнал при отмене."""
        from PySide6.QtCore import QPointF
        scene = GraphScene()
        received = []
        scene.add_process_requested.connect(lambda x, y: received.append((x, y)))

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        with patch("multiprocess_prototype_2.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
            mock_menu = MockMenu.return_value
            add_action = MagicMock()
            mock_menu.addAction.return_value = add_action
            mock_menu.exec.return_value = None  # пользователь нажал Escape

            scene._show_background_menu(mock_event, QPointF(0.0, 0.0))

        assert received == []
