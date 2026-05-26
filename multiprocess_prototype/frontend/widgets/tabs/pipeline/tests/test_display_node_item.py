"""Тесты для DisplayNodeItem и DisplayNodeData."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor

from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.constants import (
    DISPLAY_CATEGORY_COLOR,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.display_node_item import (
    DisplayNodeData,
    DisplayNodeItem,
)
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene


class TestDisplayNodeCreation:
    """Проверка создания узла и базовых атрибутов."""

    def test_display_node_creation(self, qtbot):
        """Узел создаётся; data.display_id и data.display_name корректны."""
        data = DisplayNodeData(
            node_id="disp1",
            display_id="main_output",
            display_name="Главный экран",
            x=100.0,
            y=200.0,
        )
        item = DisplayNodeItem(data)

        assert item.node_id == "disp1"
        assert item.data.display_id == "main_output"
        assert item.data.display_name == "Главный экран"
        assert item.data.category == "display"
        assert item.pos().x() == pytest.approx(100.0)
        assert item.pos().y() == pytest.approx(200.0)

    def test_display_node_data_defaults(self, qtbot):
        """DisplayNodeData: поля x, y, display_name имеют дефолты."""
        data = DisplayNodeData(node_id="d0", display_id="ch0")
        assert data.display_name == ""
        assert data.x == pytest.approx(0.0)
        assert data.y == pytest.approx(0.0)
        assert data.category == "display"


class TestDisplayNodePorts:
    """Проверка количества и типов портов."""

    def test_display_node_one_input_port(self, qtbot):
        """Ровно 1 входной порт «frame», 0 выходных."""
        data = DisplayNodeData(node_id="disp1", display_id="ch1")
        item = DisplayNodeItem(data)

        assert len(item.input_ports) == 1
        assert len(item.output_ports) == 0

    def test_input_port_name_is_frame(self, qtbot):
        """Endpoint входного порта содержит «frame»."""
        data = DisplayNodeData(node_id="disp2", display_id="ch2")
        item = DisplayNodeItem(data)

        port = item.input_ports[0]
        assert port.endpoint == "disp2.frame"
        assert port.is_input is True
        assert port.is_output is False


class TestDisplayNodeSetDisplay:
    """Проверка метода set_display."""

    def test_set_display_updates_subtitle(self, qtbot):
        """После set_display("disp2", "Debug") subtitle отражает «Debug»."""
        data = DisplayNodeData(node_id="d1", display_id="old_id", display_name="Old Name")
        item = DisplayNodeItem(data)

        item.set_display("disp2", "Debug")

        assert item.data.display_id == "disp2"
        assert item.data.display_name == "Debug"
        # subtitle_text должен показывать новое имя
        assert item._subtitle_text.toPlainText() == "Debug"

    def test_set_display_fallback_to_id(self, qtbot):
        """Если display_name пустое — subtitle показывает display_id."""
        data = DisplayNodeData(node_id="d2", display_id="ch_a", display_name="Some Name")
        item = DisplayNodeItem(data)

        item.set_display("ch_b", "")

        assert item._subtitle_text.toPlainText() == "ch_b"

    def test_display_id_property(self, qtbot):
        """Свойство display_id возвращает актуальный ID (для round-trip)."""
        data = DisplayNodeData(node_id="d3", display_id="orig")
        item = DisplayNodeItem(data)

        item.set_display("updated_id", "")

        assert item.display_id == "updated_id"


class TestDisplayNodeColor:
    """Проверка цвета фона узла."""

    def test_display_node_color(self, qtbot):
        """Цвет фона — DISPLAY_CATEGORY_COLOR (#2e7d32)."""
        data = DisplayNodeData(node_id="d4", display_id="ch4")
        item = DisplayNodeItem(data)

        expected_color = QColor(DISPLAY_CATEGORY_COLOR)
        actual_color = item.brush().color()

        assert actual_color.name() == expected_color.name()


class TestDisplayNodeInScene:
    """Проверка добавления узла в GraphScene."""

    def test_display_node_in_scene(self, qtbot):
        """Узел добавляется в GraphScene без падений."""
        scene = GraphScene()
        data = DisplayNodeData(
            node_id="disp_scene",
            display_id="output_ch",
            display_name="Test Display",
            x=50.0,
            y=80.0,
        )
        item = DisplayNodeItem(data)
        # Добавляем напрямую через addItem (GraphScene пока не имеет add_display_node)
        scene.addItem(item)

        # Узел находится на сцене
        assert item.scene() is scene

        # Порт тоже привязан к родителю
        assert len(item.input_ports) == 1
        assert item.input_ports[0].parentItem() is item
