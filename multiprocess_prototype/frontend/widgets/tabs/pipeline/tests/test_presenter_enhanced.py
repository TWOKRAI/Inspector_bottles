"""Тесты Enhanced PipelinePresenter — Phase 13.6, мигрировано на AppServices (Task E.1).

Проверяют координацию PipelineModel + ActionBus + GraphScene + TopologyHolder.
Без Qt — все зависимости замоканы.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.domain.entities import Topology
from multiprocess_prototype.domain.event_bus import EventBus
from multiprocess_prototype.domain.events import TopologyReplaced
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.node_item import NodeData

from ._helpers import make_pipeline_services


# ------------------------------------------------------------------ #
#  Тесты загрузки                                                     #
# ------------------------------------------------------------------ #


class TestLoad:
    def test_load_topology(self):
        """load_topology_from_config загружает процессы в модель."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        nodes, edges = p.load_topology_from_config()

        assert len(nodes) == 2
        assert len(edges) == 1
        # Модель тоже обновлена
        assert "camera" in p.model.get_process_names()
        assert "processor" in p.model.get_process_names()

    def test_model_round_trip(self):
        """model.to_topology_dict() содержит загруженные данные."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        topo = p.model.to_topology_dict()
        assert len(topo.get("processes", [])) == 2
        assert len(topo.get("wires", [])) == 1


# ------------------------------------------------------------------ #
#  Тесты мутаций                                                      #
# ------------------------------------------------------------------ #


class TestMutations:
    def test_add_process_from_plugin(self):
        """add_process_from_plugin добавляет процесс в модель."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        name = p.add_process_from_plugin("my_plugin", x=100.0, y=200.0)
        assert name == "my-plugin"
        assert "my-plugin" in p.model.get_process_names()

    def test_add_process_unique_name(self):
        """Дубликат имени → автоинкремент."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        name1 = p.add_process_from_plugin("test_plugin")
        name2 = p.add_process_from_plugin("test_plugin")
        assert name1 == "test-plugin"
        assert name2 == "test-plugin_1"
        assert len(p.model.get_process_names()) == 2

    def test_remove_selected(self):
        """remove_selected удаляет процесс из модели."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["camera"])
        names = p.model.get_process_names()
        assert "camera" not in names
        assert "processor" in names

    def test_remove_selected_display_node(self):
        """remove_selected различает display-узел и удаляет его через remove_display."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        # Добавляем display-узел и wire к нему
        p.model.add_display("disp1", "main_output", "Main Display")
        p.model.add_wire("processor.color_mask.frame", "display.disp1.frame")

        assert len(p.model.get_displays()) == 1
        assert len(p.model.get_wires()) == 2  # исходный + к display

        p.remove_selected(["disp1"])

        # display удалён из модели, каскадно ушёл wire к нему
        assert len(p.model.get_displays()) == 0
        wires = p.model.get_wires()
        assert all("display." not in w.get("target", "") for w in wires)
        # процессы не тронуты
        assert "processor" in p.model.get_process_names()

    def test_add_wire(self):
        """add_wire добавляет wire через модель."""
        services = make_pipeline_services(
            topology={
                "processes": [
                    {"process_name": "a", "plugins": []},
                    {"process_name": "b", "plugins": []},
                ],
                "wires": [],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        result = p.add_wire("a.out.data", "b.in.data")
        assert result is True
        assert len(p.model.get_wires()) == 1

    def test_add_wire_cycle_rejected(self):
        """Цикл → add_wire возвращает False."""
        services = make_pipeline_services(
            topology={
                "processes": [
                    {"process_name": "a", "plugins": []},
                    {"process_name": "b", "plugins": []},
                ],
                "wires": [
                    {"source": "a.out.data", "target": "b.in.data"},
                ],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        # b → a создаёт цикл
        result = p.add_wire("b.out.data", "a.in.data")
        assert result is False


# ------------------------------------------------------------------ #
#  Тесты валидации                                                    #
# ------------------------------------------------------------------ #


class TestValidation:
    def test_validate(self):
        """validate() возвращает список ошибок через модель."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        errors = p.validate()
        # Модель содержит корректную topology — ошибки могут быть
        # только "Изолированный процесс" если оба не orphans
        assert isinstance(errors, list)


# ------------------------------------------------------------------ #
#  Тесты auto-layout                                                  #
# ------------------------------------------------------------------ #


class TestAutoLayout:
    def test_auto_layout(self, qtbot):
        """auto_layout_scene не падает (с mock scene)."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        scene = MagicMock()
        scene.get_node.return_value = MagicMock()
        p.set_scene(scene)

        # Не должно упасть
        p.auto_layout_scene()


# ------------------------------------------------------------------ #
#  Тесты signal suppression                                           #
# ------------------------------------------------------------------ #


class TestSignalSuppression:
    def test_block_signals(self):
        """_block_signals подавляет и восстанавливает флаг."""
        services = make_pipeline_services()
        p = PipelinePresenter(services)

        assert not p.is_suppressed
        with p._block_signals():
            assert p.is_suppressed
        assert not p.is_suppressed

    def test_on_topology_replaced(self):
        """TopologyReplaced → handler тянет топологию из repo и обновляет модель."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        # Меняем живой источник (repo), затем эмитим TopologyReplaced
        services.topology.save(
            Topology.from_dict(
                {
                    "processes": [{"process_name": "new_proc", "plugins": []}],
                    "wires": [],
                }
            )
        )
        p._on_topology_replaced(TopologyReplaced(reason="test"))

        assert "new_proc" in p.model.get_process_names()

    def test_external_change_suppressed(self):
        """Подавленный handler не обновляет модель (suppress guard)."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        services.topology.save(
            Topology.from_dict(
                {
                    "processes": [{"process_name": "x", "plugins": []}],
                    "wires": [],
                }
            )
        )
        with p._block_signals():
            p._on_topology_replaced(TopologyReplaced(reason="test"))

        # Модель не должна обновиться (suppress был активен)
        assert "x" not in p.model.get_process_names()

    def test_topology_replaced_via_eventbus(self):
        """Wiring: presenter подписан на TopologyReplaced через services.events.

        Реальный EventBus: publish(TopologyReplaced) → handler presenter'а
        срабатывает и тянет новую топологию из repo (проверяет саму подписку G.1).
        """
        bus = EventBus()
        services = make_pipeline_services(topology={"processes": [], "wires": []}, events=bus)
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        services.topology.save(
            Topology.from_dict(
                {
                    "processes": [{"process_name": "via_bus", "plugins": []}],
                    "wires": [],
                }
            )
        )
        bus.publish(TopologyReplaced(reason="recipe_launch"))

        assert "via_bus" in p.model.get_process_names()


# ------------------------------------------------------------------ #
#  Тесты ActionBus интеграция                                        #
# ------------------------------------------------------------------ #


class TestActionBus:
    def test_add_process_with_action_bus(self):
        """ActionBus.execute вызывается при add_process_from_plugin."""
        mock_bus = MagicMock()
        services = make_pipeline_services(
            topology={"processes": [], "wires": []},
            action_bus=mock_bus,
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_process_from_plugin("my_plugin")
        mock_bus.execute.assert_called_once()


# ------------------------------------------------------------------ #
#  Тесты GUI positions                                                #
# ------------------------------------------------------------------ #


class TestGuiPositions:
    def test_gui_positions_stored(self):
        """add_process_from_plugin сохраняет позицию в _gui_positions."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_process_from_plugin("test_plugin", x=150.0, y=250.0)
        assert p._gui_positions["test-plugin"] == (150.0, 250.0)

    def test_on_node_moved(self):
        """on_node_moved обновляет позицию."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_process_from_plugin("test_plugin")
        p.on_node_moved("test-plugin", 300.0, 400.0)
        assert p._gui_positions["test-plugin"] == (300.0, 400.0)

    def test_on_node_moved_suppressed(self):
        """on_node_moved не обновляет при suppression."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()
        p.add_process_from_plugin("test_plugin")

        with p._block_signals():
            p.on_node_moved("test-plugin", 999.0, 999.0)

        # Позиция не должна обновиться до (999, 999)
        assert p._gui_positions["test-plugin"] == (0.0, 0.0)


# ------------------------------------------------------------------ #
#  Тесты scene интеграция                                             #
# ------------------------------------------------------------------ #


class TestSceneIntegration:
    def test_scene_updated_on_add(self):
        """scene.add_node вызывается при add_process_from_plugin."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        mock_scene = MagicMock()
        p.set_scene(mock_scene)

        p.add_process_from_plugin("my_plugin", x=50.0, y=60.0)
        mock_scene.add_node.assert_called_once()

        # Проверить переданные данные
        call_args = mock_scene.add_node.call_args
        node_data = call_args[0][0]
        assert isinstance(node_data, NodeData)
        assert node_data.node_id == "my-plugin"
        assert node_data.x == 50.0
        assert node_data.y == 60.0
