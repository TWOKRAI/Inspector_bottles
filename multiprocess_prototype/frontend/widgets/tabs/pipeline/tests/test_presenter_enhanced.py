"""Тесты Enhanced PipelinePresenter — Phase 13.6.

Проверяют координацию PipelineModel + ActionBus + GraphScene + TopologyHolder.
Без Qt — все зависимости замоканы.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.node_item import NodeData
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.edge_item import EdgeData


# ------------------------------------------------------------------ #
#  Фикстуры                                                           #
# ------------------------------------------------------------------ #

def _make_enhanced_ctx(topology=None):
    """Создать mock AppContext с полным набором extras."""
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


# ------------------------------------------------------------------ #
#  Тесты загрузки                                                     #
# ------------------------------------------------------------------ #

class TestLoad:
    def test_load_topology(self):
        """load_topology_from_config загружает процессы в модель."""
        ctx = _make_enhanced_ctx()
        p = PipelinePresenter(ctx)
        nodes, edges = p.load_topology_from_config()

        assert len(nodes) == 2
        assert len(edges) == 1
        # Модель тоже обновлена
        assert "camera" in p.model.get_process_names()
        assert "processor" in p.model.get_process_names()

    def test_model_round_trip(self):
        """model.to_topology_dict() содержит загруженные данные."""
        ctx = _make_enhanced_ctx()
        p = PipelinePresenter(ctx)
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
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        name = p.add_process_from_plugin("my_plugin", x=100.0, y=200.0)
        assert name == "my-plugin"
        assert "my-plugin" in p.model.get_process_names()

    def test_add_process_unique_name(self):
        """Дубликат имени → автоинкремент."""
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        name1 = p.add_process_from_plugin("test_plugin")
        name2 = p.add_process_from_plugin("test_plugin")
        assert name1 == "test-plugin"
        assert name2 == "test-plugin_1"
        assert len(p.model.get_process_names()) == 2

    def test_remove_selected(self):
        """remove_selected удаляет процесс из модели."""
        ctx = _make_enhanced_ctx()
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        p.remove_selected(["camera"])
        names = p.model.get_process_names()
        assert "camera" not in names
        assert "processor" in names

    def test_add_wire(self):
        """add_wire добавляет wire через модель."""
        ctx = _make_enhanced_ctx(topology={
            "processes": [
                {"process_name": "a", "plugins": []},
                {"process_name": "b", "plugins": []},
            ],
            "wires": [],
        })
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        result = p.add_wire("a.out.data", "b.in.data")
        assert result is True
        assert len(p.model.get_wires()) == 1

    def test_add_wire_cycle_rejected(self):
        """Цикл → add_wire возвращает False."""
        ctx = _make_enhanced_ctx(topology={
            "processes": [
                {"process_name": "a", "plugins": []},
                {"process_name": "b", "plugins": []},
            ],
            "wires": [
                {"source": "a.out.data", "target": "b.in.data"},
            ],
        })
        p = PipelinePresenter(ctx)
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
        ctx = _make_enhanced_ctx()
        p = PipelinePresenter(ctx)
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
        ctx = _make_enhanced_ctx()
        p = PipelinePresenter(ctx)
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
        ctx = _make_enhanced_ctx()
        p = PipelinePresenter(ctx)

        assert not p.is_suppressed
        with p._block_signals():
            assert p.is_suppressed
        assert not p.is_suppressed

    def test_on_topology_changed_external(self):
        """Внешнее изменение topology обновляет модель."""
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        new_topo = {
            "processes": [
                {"process_name": "new_proc", "plugins": []},
            ],
            "wires": [],
        }
        p._on_topology_changed_external(new_topo)

        assert "new_proc" in p.model.get_process_names()

    def test_external_change_suppressed(self):
        """Подавленный callback не обновляет модель."""
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        with p._block_signals():
            p._on_topology_changed_external({
                "processes": [{"process_name": "x", "plugins": []}],
                "wires": [],
            })

        # Модель не должна обновиться (suppress был активен)
        assert "x" not in p.model.get_process_names()


# ------------------------------------------------------------------ #
#  Тесты ActionBus интеграция                                        #
# ------------------------------------------------------------------ #

class TestActionBus:
    def test_add_process_with_action_bus(self):
        """ActionBus.execute вызывается при add_process_from_plugin."""
        mock_bus = MagicMock()
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        ctx.action_bus.return_value = mock_bus
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        p.add_process_from_plugin("my_plugin")
        mock_bus.execute.assert_called_once()


# ------------------------------------------------------------------ #
#  Тесты GUI positions                                                #
# ------------------------------------------------------------------ #

class TestGuiPositions:
    def test_gui_positions_stored(self):
        """add_process_from_plugin сохраняет позицию в _gui_positions."""
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        p.add_process_from_plugin("test_plugin", x=150.0, y=250.0)
        assert p._gui_positions["test-plugin"] == (150.0, 250.0)

    def test_on_node_moved(self):
        """on_node_moved обновляет позицию."""
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
        p.load_topology_from_config()

        p.add_process_from_plugin("test_plugin")
        p.on_node_moved("test-plugin", 300.0, 400.0)
        assert p._gui_positions["test-plugin"] == (300.0, 400.0)

    def test_on_node_moved_suppressed(self):
        """on_node_moved не обновляет при suppression."""
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
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
        ctx = _make_enhanced_ctx(topology={"processes": [], "wires": []})
        p = PipelinePresenter(ctx)
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
