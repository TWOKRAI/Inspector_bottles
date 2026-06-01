"""Тесты контекстных меню GraphScene."""

import pytest
from unittest.mock import MagicMock, patch

from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.node_item import NodeData
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.edge_item import EdgeData
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.display_node_item import (
    DisplayNodeData,
)


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
        with patch("multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
            mock_menu = MockMenu.return_value
            delete_action = MagicMock()
            inspect_action = MagicMock()
            lock_action = MagicMock()
            # Порядок пунктов для плагин-ноды: Inspect, Зафиксировать, Delete.
            mock_menu.addAction.side_effect = [inspect_action, lock_action, delete_action]
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

        with patch("multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
            mock_menu = MockMenu.return_value
            inspect_action = MagicMock()
            delete_action = MagicMock()
            lock_action = MagicMock()
            # Порядок пунктов для плагин-ноды: Inspect, Зафиксировать, Delete.
            mock_menu.addAction.side_effect = [inspect_action, lock_action, delete_action]
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

        with patch("multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
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

        with patch("multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
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

        with patch("multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu") as MockMenu:
            mock_menu = MockMenu.return_value
            add_action = MagicMock()
            mock_menu.addAction.return_value = add_action
            mock_menu.exec.return_value = None  # пользователь нажал Escape

            scene._show_background_menu(mock_event, QPointF(0.0, 0.0))

        assert received == []


class TestDisplaySubmenu:
    """Task 4.2a-c: тесты подменю «Add Display →» в _show_background_menu."""

    def _make_display_mock_menu(self, display_action=None, exec_result=None):
        """Хелпер: возвращает (MockMenu-класс-patch, display_act) для _show_background_menu.

        Архитектура реального кода:
          menu = QMenu()                          <- MockMenu()
          add_action = menu.addAction(...)        <- возвращает add_action mock
          display_menu = menu.addMenu(...)        <- возвращает submenu mock
          act = display_menu.addAction(display_name)  <- display-action с .data() = display_id
          action = menu.exec(...)                 <- exec_result
        """
        import unittest.mock as um

        display_act = display_action if display_action is not None else MagicMock()
        submenu_mock = MagicMock()
        submenu_mock.addAction.return_value = display_act

        mock_menu_instance = MagicMock()
        add_process_action = MagicMock()
        mock_menu_instance.addAction.return_value = add_process_action
        mock_menu_instance.addMenu.return_value = submenu_mock
        mock_menu_instance.exec.return_value = exec_result

        MockMenuClass = um.MagicMock(return_value=mock_menu_instance)

        return MockMenuClass, mock_menu_instance, submenu_mock, display_act, add_process_action

    def test_display_action_emits_add_display_requested(self, qtbot):
        """set_display_channels + выбор display-action → эмиссия add_display_requested(display_id, x, y)."""
        from PySide6.QtCore import QPointF

        scene = GraphScene()
        scene.set_display_channels([("main", "Основной")])

        received = []
        scene.add_display_requested.connect(lambda did, x, y: received.append((did, x, y)))

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()
        pos = QPointF(300.0, 400.0)

        # display_act — имитирует action с data() = "main"
        display_act = MagicMock()
        display_act.data.return_value = "main"

        MockMenuClass, mock_menu_instance, submenu_mock, _, _ = self._make_display_mock_menu(
            display_action=display_act,
            exec_result=display_act,  # пользователь выбрал display-action
        )

        with patch(
            "multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu",
            MockMenuClass,
        ):
            scene._show_background_menu(mock_event, pos)

        assert len(received) == 1
        did, x, y = received[0]
        assert did == "main"
        assert x == pytest.approx(300.0)
        assert y == pytest.approx(400.0)

    def test_empty_channels_display_submenu_disabled(self, qtbot):
        """Пустой список каналов → подменю «Add Display →» disabled."""
        from PySide6.QtCore import QPointF

        scene = GraphScene()
        scene.set_display_channels([])  # пустой список

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        submenu_mock = MagicMock()
        mock_menu_instance = MagicMock()
        mock_menu_instance.addAction.return_value = MagicMock()
        mock_menu_instance.addMenu.return_value = submenu_mock
        mock_menu_instance.exec.return_value = None

        MockMenuClass = MagicMock(return_value=mock_menu_instance)

        with patch(
            "multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu",
            MockMenuClass,
        ):
            scene._show_background_menu(mock_event, QPointF(0.0, 0.0))

        # Подменю должно быть задизейблено (setEnabled(False) вызван)
        submenu_mock.setEnabled.assert_called_once_with(False)
        # И никаких display-actions не должно быть добавлено
        submenu_mock.addAction.assert_not_called()

    def test_cancel_menu_does_not_emit_add_display(self, qtbot):
        """Отмена контекстного меню (exec → None) → add_display_requested НЕ эмитится."""
        from PySide6.QtCore import QPointF

        scene = GraphScene()
        scene.set_display_channels([("main", "Основной"), ("debug", "Отладочный")])

        received_display = []
        received_process = []
        scene.add_display_requested.connect(lambda did, x, y: received_display.append((did, x, y)))
        scene.add_process_requested.connect(lambda x, y: received_process.append((x, y)))

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        display_act = MagicMock()
        display_act.data.return_value = "main"

        MockMenuClass, mock_menu_instance, submenu_mock, _, _ = self._make_display_mock_menu(
            display_action=display_act,
            exec_result=None,  # пользователь нажал Escape / закрыл меню
        )

        with patch(
            "multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu",
            MockMenuClass,
        ):
            scene._show_background_menu(mock_event, QPointF(50.0, 60.0))

        assert received_display == [], "add_display_requested не должен эмититься при отмене"
        assert received_process == [], "add_process_requested не должен эмититься при отмене"

    def test_empty_display_name_falls_back_to_id(self, qtbot):
        """#11: пустой display_name → подпись action = display_id (fallback).

        _show_background_menu строит `addAction(display_name or display_id)`. Проверяем,
        что при пустом имени подпись = display_id, а setData получает корректный id.
        """
        from PySide6.QtCore import QPointF

        scene = GraphScene()
        scene.set_display_channels([("raw_cam", "")])  # пустое display_name

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        # display-action, который вернётся из submenu.addAction
        display_act = MagicMock()
        submenu_mock = MagicMock()
        submenu_mock.addAction.return_value = display_act

        mock_menu_instance = MagicMock()
        mock_menu_instance.addAction.return_value = MagicMock()  # «Add Process...»
        mock_menu_instance.addMenu.return_value = submenu_mock
        mock_menu_instance.exec.return_value = None  # меню закрыто без выбора

        MockMenuClass = MagicMock(return_value=mock_menu_instance)

        with patch(
            "multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu",
            MockMenuClass,
        ):
            scene._show_background_menu(mock_event, QPointF(0.0, 0.0))

        # Подпись пункта = display_id («raw_cam»), т.к. display_name пустое
        submenu_mock.addAction.assert_called_once_with("raw_cam")
        # И setData получил правильный display_id
        display_act.setData.assert_called_once_with("raw_cam")


class TestDisplayNodeContextMenu:
    """Follow-up #6: контекстное меню для DisplayNodeItem (правый клик по display-боксу)."""

    def _make_node_menu_mock(self, exec_result_side="delete"):
        """Хелпер: создать mock QMenu для _show_node_menu.

        Архитектура _show_node_menu:
          menu = QMenu()
          inspect_action = menu.addAction("Inspect")    <- 1-й addAction
          menu.addSeparator()
          delete_action = menu.addAction("Delete")      <- 2-й addAction
          action = menu.exec(...)                       <- exec_result

        exec_result_side: "delete" | "inspect" | "cancel"
        """
        mock_menu = MagicMock()
        inspect_action = MagicMock(name="inspect_action")
        delete_action = MagicMock(name="delete_action")
        mock_menu.addAction.side_effect = [inspect_action, delete_action]

        if exec_result_side == "delete":
            mock_menu.exec.return_value = delete_action
        elif exec_result_side == "inspect":
            mock_menu.exec.return_value = inspect_action
        else:
            mock_menu.exec.return_value = None

        MockMenuClass = MagicMock(return_value=mock_menu)
        return MockMenuClass, mock_menu, inspect_action, delete_action

    def test_display_node_delete_emits_node_delete_requested(self, qtbot):
        """Правый клик по DisplayNodeItem + Delete → эмитится node_delete_requested(display_id)."""
        scene = GraphScene()
        data = DisplayNodeData(node_id="main", display_id="main", display_name="Основной")
        display_item = scene.add_display_node(data)

        received = []
        scene.node_delete_requested.connect(lambda nid: received.append(nid))

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        MockMenuClass, _, _, _ = self._make_node_menu_mock("delete")
        with patch(
            "multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu",
            MockMenuClass,
        ):
            scene._show_node_menu(mock_event, display_item)

        assert received == ["main"], f"node_delete_requested должен эмитится с display_id='main', получено: {received}"

    def test_display_node_inspect_emits_node_inspect_requested(self, qtbot):
        """Правый клик по DisplayNodeItem + Inspect → эмитится node_inspect_requested(display_id)."""
        scene = GraphScene()
        data = DisplayNodeData(node_id="debug", display_id="debug", display_name="Отладочный")
        display_item = scene.add_display_node(data)

        received = []
        scene.node_inspect_requested.connect(lambda nid: received.append(nid))

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        MockMenuClass, _, _, _ = self._make_node_menu_mock("inspect")
        with patch(
            "multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu",
            MockMenuClass,
        ):
            scene._show_node_menu(mock_event, display_item)

        assert received == ["debug"], (
            f"node_inspect_requested должен эмитится с display_id='debug', получено: {received}"
        )

    def test_context_menu_event_calls_show_node_menu_for_display_item(self, qtbot):
        """contextMenuEvent для DisplayNodeItem вызывает _show_node_menu (не фоновое меню)."""
        scene = GraphScene()
        data = DisplayNodeData(node_id="cam", display_id="cam", display_name="Камера")
        scene.add_display_node(data)

        # Отслеживаем, что _show_node_menu был вызван, а фоновое меню — нет.
        # scene одноразовая (новый инстанс на тест) → восстанавливать методы не нужно.
        calls = {"node": 0, "bg": 0}

        def _spy_node_menu(event, item):
            calls["node"] += 1

        def _spy_bg_menu(event, pos):
            calls["bg"] += 1

        scene._show_node_menu = _spy_node_menu
        scene._show_background_menu = _spy_bg_menu

        # Создаём mock event — itemAt возвращает display_item напрямую
        from PySide6.QtCore import QPointF

        mock_event = MagicMock()
        mock_event.scenePos.return_value = QPointF(50.0, 50.0)
        mock_event.screenPos.return_value = MagicMock()

        # Патчим itemAt и views — scene не привязана к GraphView
        with (
            patch.object(scene, "itemAt", return_value=scene.get_node("cam")),
            patch.object(scene, "views", return_value=[MagicMock()]),
        ):
            scene.contextMenuEvent(mock_event)

        assert calls["node"] == 1, "contextMenuEvent должен вызвать _show_node_menu для DisplayNodeItem"
        assert calls["bg"] == 0, "contextMenuEvent НЕ должен вызывать фоновое меню для DisplayNodeItem"

    def test_display_node_cancel_menu_no_signals(self, qtbot):
        """Отмена контекстного меню по DisplayNodeItem → сигналы НЕ эмитятся."""
        scene = GraphScene()
        data = DisplayNodeData(node_id="x", display_id="x", display_name="X")
        display_item = scene.add_display_node(data)

        received_delete = []
        received_inspect = []
        scene.node_delete_requested.connect(lambda nid: received_delete.append(nid))
        scene.node_inspect_requested.connect(lambda nid: received_inspect.append(nid))

        mock_event = MagicMock()
        mock_event.screenPos.return_value = MagicMock()

        MockMenuClass, _, _, _ = self._make_node_menu_mock("cancel")
        with patch(
            "multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene.QMenu",
            MockMenuClass,
        ):
            scene._show_node_menu(mock_event, display_item)

        assert received_delete == [], "При отмене node_delete_requested НЕ должен эмититься"
        assert received_inspect == [], "При отмене node_inspect_requested НЕ должен эмититься"
