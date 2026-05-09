"""Тесты round-trip YAML с позициями нод."""
import pytest
from unittest.mock import MagicMock

from multiprocess_prototype_2.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter


def _make_ctx(topology=None):
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
    ctx.action_bus.return_value = None
    ctx.topology_holder.return_value = None
    ctx.topology_bridge.return_value = None
    return ctx


class TestYamlPositions:
    def test_export_includes_gui_positions(self):
        """export_topology_with_positions включает позиции."""
        ctx = _make_ctx()
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        # Установить позиции
        p._gui_positions["camera"] = (100.0, 200.0)
        p._gui_positions["processor"] = (300.0, 200.0)

        topo = p.export_topology_with_positions()
        assert "metadata" in topo
        assert "gui_positions" in topo["metadata"]
        assert topo["metadata"]["gui_positions"]["camera"] == [100.0, 200.0]
        assert topo["metadata"]["gui_positions"]["processor"] == [300.0, 200.0]

    def test_round_trip_positions(self):
        """Позиции сохраняются и восстанавливаются."""
        ctx1 = _make_ctx()
        p1 = PipelinePresenter(ctx1)
        p1.load_topology_from_config()
        p1._gui_positions["camera"] = (150.0, 250.0)
        p1._gui_positions["processor"] = (400.0, 250.0)

        exported = p1.export_topology_with_positions()

        # Загрузить в новый presenter
        ctx2 = _make_ctx(topology=exported)
        p2 = PipelinePresenter(ctx2)
        p2.load_topology_from_config()

        assert p2._gui_positions["camera"] == (150.0, 250.0)
        assert p2._gui_positions["processor"] == (400.0, 250.0)

    def test_export_without_positions(self):
        """Экспорт без позиций — пустой gui_positions."""
        ctx = _make_ctx()
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        topo = p.export_topology_with_positions()
        # gui_positions может быть пустым если позиции не установлены
        assert "metadata" in topo

    def test_load_without_metadata(self):
        """Загрузка topology без metadata — нет ошибок."""
        ctx = _make_ctx(topology={
            "processes": [{"process_name": "test", "plugins": []}],
            "wires": [],
        })
        p = PipelinePresenter(ctx)
        nodes, edges = p.load_topology_from_config()
        assert len(nodes) == 1

    def test_positions_in_node_data(self):
        """Позиции передаются в NodeData при конвертации."""
        ctx = _make_ctx()
        p = PipelinePresenter(ctx)
        p._gui_positions["camera"] = (100.0, 200.0)

        topology = ctx.config["topology"]
        nodes, edges = p._topology_to_graph(topology)

        camera_node = next(n for n in nodes if n.node_id == "camera")
        assert camera_node.x == 100.0
        assert camera_node.y == 200.0
