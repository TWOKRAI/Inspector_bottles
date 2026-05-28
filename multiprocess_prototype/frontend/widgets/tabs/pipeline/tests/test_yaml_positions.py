"""Тесты round-trip YAML с позициями нод. Task E.1: AppServices."""

from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services


class TestYamlPositions:
    def test_export_includes_gui_positions(self):
        """export_topology_with_positions включает позиции."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
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
        services1 = make_pipeline_services()
        p1 = PipelinePresenter(services1)
        p1.load_topology_from_config()
        p1._gui_positions["camera"] = (150.0, 250.0)
        p1._gui_positions["processor"] = (400.0, 250.0)

        exported = p1.export_topology_with_positions()

        # Загрузить в новый presenter
        services2 = make_pipeline_services(topology=exported)
        p2 = PipelinePresenter(services2)
        p2.load_topology_from_config()

        assert p2._gui_positions["camera"] == (150.0, 250.0)
        assert p2._gui_positions["processor"] == (400.0, 250.0)

    def test_export_without_positions(self):
        """Экспорт без позиций — пустой gui_positions."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        topo = p.export_topology_with_positions()
        assert "metadata" in topo

    def test_load_without_metadata(self):
        """Загрузка topology без metadata — нет ошибок."""
        services = make_pipeline_services(
            topology={
                "processes": [{"process_name": "test", "plugins": []}],
                "wires": [],
            }
        )
        p = PipelinePresenter(services)
        nodes, edges = p.load_topology_from_config()
        assert len(nodes) == 1

    def test_positions_in_node_data(self):
        """Позиции передаются в NodeData при конвертации."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        p._gui_positions["camera"] = (100.0, 200.0)

        topology = services.topology.load().to_dict()
        nodes, edges = p._topology_to_graph(topology)

        camera_node = next(n for n in nodes if n.node_id == "camera")
        assert camera_node.x == 100.0
        assert camera_node.y == 200.0
