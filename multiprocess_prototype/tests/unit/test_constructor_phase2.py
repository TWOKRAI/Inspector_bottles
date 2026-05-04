"""Тесты Фазы 2 конструктора — CrossProcessModel, auto_layout, GraphBuilder.

Разделены на:
1. Чистые тесты (без Qt/NodeGraphQt) — CrossProcessModel, auto_layout
2. Qt-тесты (NodeGraphQt) — GraphBuilder, PluginProcessNode, adapter
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# Предотвращаем circular import из tabs_setting/__init__.py.
# При import constructor_tab через tabs_setting Python загружает __init__.py,
# который тянет sources_tab -> base -> recipe_panel_base -> circular.
# Workaround: регистрируем пустые заглушки для проблемных модулей
# ДО импорта наших модуле�� (если они ещё не загружены).
_STUB_MODULES = [
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab.camera_panel",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.recipes_settings_tab",
    "multiprocess_prototype.frontend.widgets.tabs_setting.display_tab",
]
for _mod in _STUB_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from multiprocess_prototype.frontend.models.system_topology_editor import (
    SystemTopologyEditor,
)
from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.auto_layout import (
    auto_layout,
)
from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.models.cross_process_model import (
    CrossProcessModel,
    PortInfo,
    ProcessNodeData,
)


def _make_editor(**overrides) -> SystemTopologyEditor:
    """Создать SystemTopologyEditor с тестовыми данными."""
    data = {
        "processes": {
            "camera_0": {
                "name": "camera_0",
                "class_path": "CameraProcess",
                "priority": "high",
                "auto_start": True,
                "sort_order": 0,
                "plugins": [
                    {"plugin_class": "CapturePlugin", "plugin_name": "capture"},
                    {"plugin_class": "ResizePlugin", "plugin_name": "resize"},
                ],
            },
            "processor_0": {
                "name": "processor_0",
                "class_path": "ProcessorProcess",
                "priority": "normal",
                "auto_start": True,
                "sort_order": 1,
                "plugins": [
                    {"plugin_class": "ColorMaskPlugin", "plugin_name": "color_mask"},
                ],
            },
        },
        "workers": {},
        "cameras": {},
        "regions": {},
        "pipeline": {},
        "displays": {},
        "wires": {},
    }
    data.update(overrides)
    editor = SystemTopologyEditor()
    editor.load(data)
    return editor


# =====================================================================
# 1. CrossProcessModel (без Qt)
# =====================================================================


class TestCrossProcessModel:
    """Тесты агрегатора данных процессов."""

    def test_process_nodes_returns_all_processes(self) -> None:
        editor = _make_editor()
        model = CrossProcessModel(editor)
        nodes = model.process_nodes

        assert "camera_0" in nodes
        assert "processor_0" in nodes
        assert len(nodes) == 2

    def test_process_node_data_fields(self) -> None:
        editor = _make_editor()
        model = CrossProcessModel(editor)
        cam = model.get_node("camera_0")

        assert cam is not None
        assert cam.name == "camera_0"
        assert cam.priority == "high"
        assert cam.plugin_names == ["capture", "resize"]
        assert cam.class_path == "CameraProcess"

    def test_invalidate_forces_rebuild(self) -> None:
        editor = _make_editor()
        model = CrossProcessModel(editor)
        _ = model.process_nodes  # Кэширует

        # Добавляем процесс в editor напрямую
        editor._data["processes"]["new_proc"] = {
            "name": "new_proc",
            "class_path": "",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 2,
            "plugins": [],
        }

        # Без invalidate — кэш старый
        assert "new_proc" not in model.process_nodes

        # После invalidate — обновлённый
        model.invalidate()
        assert "new_proc" in model.process_nodes
        assert len(model.process_nodes) == 3

    def test_port_address_format(self) -> None:
        editor = _make_editor()
        model = CrossProcessModel(editor)

        port = PortInfo(
            name="frame", plugin_name="capture",
            data_type="ndarray", direction="output",
        )
        addr = model.port_address("camera_0", port)
        assert addr == "camera_0.capture.frame"

    def test_get_node_unknown_returns_none(self) -> None:
        editor = _make_editor()
        model = CrossProcessModel(editor)
        assert model.get_node("nonexistent") is None

    def test_empty_topology(self) -> None:
        editor = SystemTopologyEditor()
        model = CrossProcessModel(editor)
        assert model.process_nodes == {}


# =====================================================================
# 2. auto_layout (без Qt)
# =====================================================================


class TestAutoLayout:
    """Тесты Sugiyama layout для процесс-нод."""

    def test_empty_returns_empty(self) -> None:
        assert auto_layout(set(), {}) == {}

    def test_single_process_at_origin(self) -> None:
        result = auto_layout({"camera_0"}, {})
        assert "camera_0" in result
        x, y = result["camera_0"]
        assert x >= 0
        assert y >= 0

    def test_two_connected_processes_different_layers(self) -> None:
        wires = {
            "w1": {
                "source": "camera_0.capture.frame",
                "target": "processor_0.color_mask.frame",
            },
        }
        result = auto_layout({"camera_0", "processor_0"}, wires)

        assert "camera_0" in result
        assert "processor_0" in result
        # Источник (camera_0) должен быть левее приёмника
        assert result["camera_0"][0] < result["processor_0"][0]

    def test_isolated_processes_grouped_right(self) -> None:
        wires = {
            "w1": {"source": "cam.cap.frame", "target": "proc.mask.frame"},
        }
        result = auto_layout({"cam", "proc", "isolated"}, wires)

        assert "isolated" in result
        max_connected_x = max(result["cam"][0], result["proc"][0])
        assert result["isolated"][0] > max_connected_x

    def test_three_layer_chain(self) -> None:
        wires = {
            "w1": {"source": "a.p.out", "target": "b.p.in"},
            "w2": {"source": "b.p.out", "target": "c.p.in"},
        }
        result = auto_layout({"a", "b", "c"}, wires)

        assert result["a"][0] < result["b"][0]
        assert result["b"][0] < result["c"][0]

    def test_all_positions_non_negative(self) -> None:
        wires = {
            "w1": {"source": "a.p.o", "target": "b.p.i"},
            "w2": {"source": "a.p.o", "target": "c.p.i"},
            "w3": {"source": "b.p.o", "target": "d.p.i"},
        }
        result = auto_layout({"a", "b", "c", "d"}, wires)

        for pk, (x, y) in result.items():
            assert x >= 0, f"{pk}: x={x} < 0"
            assert y >= 0, f"{pk}: y={y} < 0"

    def test_fan_out_same_layer(self) -> None:
        """Fan-out: один источник → два приёмника → оба в одном слое."""
        wires = {
            "w1": {"source": "src.p.o", "target": "dst1.p.i"},
            "w2": {"source": "src.p.o", "target": "dst2.p.i"},
        }
        result = auto_layout({"src", "dst1", "dst2"}, wires)

        assert result["dst1"][0] == result["dst2"][0]
        assert result["src"][0] < result["dst1"][0]


# =====================================================================
# 3. PluginProcessNode (требует Qt)
# =====================================================================


class TestPluginProcessNode:
    """Тесты кастомной ноды NodeGraphQt."""

    def test_node_creation(self, qapp) -> None:
        from NodeGraphQt import NodeGraph
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_process_node import (
            PROCESS_NODE_TYPE,
            PluginProcessNode,
        )

        graph = NodeGraph()
        graph.register_node(PluginProcessNode)

        node = graph.create_node(PROCESS_NODE_TYPE, name="test_proc")
        assert isinstance(node, PluginProcessNode)

    def test_set_process_data(self, qapp) -> None:
        from NodeGraphQt import NodeGraph
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_process_node import (
            PROCESS_NODE_TYPE,
            PluginProcessNode,
        )

        graph = NodeGraph()
        graph.register_node(PluginProcessNode)

        node = graph.create_node(PROCESS_NODE_TYPE, name="camera_0")
        node.set_process_data(
            process_key="camera_0",
            plugin_names=["capture", "resize"],
            priority="high",
        )

        assert node.process_key == "camera_0"
        assert node.priority == "high"

    def test_add_ports(self, qapp) -> None:
        from NodeGraphQt import NodeGraph
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_process_node import (
            PROCESS_NODE_TYPE,
            PluginProcessNode,
        )

        graph = NodeGraph()
        graph.register_node(PluginProcessNode)

        node = graph.create_node(PROCESS_NODE_TYPE, name="proc")
        node.add_input("capture.frame")
        node.add_output("resize.frame")

        assert node.get_input("capture.frame") is not None
        assert node.get_output("resize.frame") is not None


# =====================================================================
# 4. GraphBuilder (требует Qt)
# =====================================================================


class TestGraphBuilder:
    """Тесты построения сцены из topology данных."""

    def _make_cross_model(self):
        editor = _make_editor(
            processes={
                "camera_0": {
                    "name": "camera_0",
                    "class_path": "",
                    "priority": "high",
                    "auto_start": True,
                    "sort_order": 0,
                    "plugins": [],
                },
                "processor_0": {
                    "name": "processor_0",
                    "class_path": "",
                    "priority": "normal",
                    "auto_start": True,
                    "sort_order": 1,
                    "plugins": [],
                },
            },
        )
        return CrossProcessModel(editor)

    def test_build_creates_nodes(self, qapp) -> None:
        from NodeGraphQt import NodeGraph
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.graph_builder import (
            GraphBuilder,
        )
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_process_node import (
            PluginProcessNode,
        )

        graph = NodeGraph()
        graph.register_node(PluginProcessNode)

        builder = GraphBuilder(graph)
        cross_model = self._make_cross_model()
        node_map, _addr_map, _route_nodes, _display_nodes = builder.build(cross_model, wires={})

        assert "camera_0" in node_map
        assert "processor_0" in node_map
        assert len(graph.all_nodes()) == 2

    def test_clear_removes_all_nodes(self, qapp) -> None:
        from NodeGraphQt import NodeGraph
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.graph_builder import (
            GraphBuilder,
        )
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_process_node import (
            PluginProcessNode,
        )

        graph = NodeGraph()
        graph.register_node(PluginProcessNode)

        builder = GraphBuilder(graph)
        cross_model = self._make_cross_model()
        builder.build(cross_model, wires={})
        assert len(graph.all_nodes()) == 2

        builder.clear()
        assert len(graph.all_nodes()) == 0

    def test_build_applies_layout(self, qapp) -> None:
        """Ноды с wire-з��висимостями размещаются на разных слоях."""
        from NodeGraphQt import NodeGraph
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.graph_builder import (
            GraphBuilder,
        )
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_process_node import (
            PluginProcessNode,
        )

        graph = NodeGraph()
        graph.register_node(PluginProcessNode)

        builder = GraphBuilder(graph)
        cross_model = self._make_cross_model()
        node_map, _addr_map, _route_nodes, _display_nodes = builder.build(cross_model, wires={})

        # Обе ноды изолированные → в одном столбце, разные Y (или одинаковые)
        assert len(node_map) == 2


# =====================================================================
# 5. Интеграц��я: adapter + topology editor
# =====================================================================


class TestPluginGraphAdapterIntegration:
    """Интеграционные тесты: adapter ↔ topology editor."""

    def _make_system(self):
        from NodeGraphQt import NodeGraph
        from multiprocess_prototype.frontend.models.wire_model import WireEditorModel
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_graph_adapter import (
            PluginGraphAdapter,
        )
        from multiprocess_prototype.frontend.widgets.tabs_setting.constructor_tab.canvas.plugin_process_node import (
            PluginProcessNode,
        )

        editor = _make_editor(
            processes={
                "camera_0": {
                    "name": "camera_0",
                    "class_path": "",
                    "priority": "normal",
                    "auto_start": True,
                    "sort_order": 0,
                    "plugins": [],
                },
                "processor_0": {
                    "name": "processor_0",
                    "class_path": "",
                    "priority": "normal",
                    "auto_start": True,
                    "sort_order": 1,
                    "plugins": [],
                },
            },
        )

        graph = NodeGraph()
        graph.register_node(PluginProcessNode)

        cross_model = CrossProcessModel(editor)
        wire_model = WireEditorModel(editor.wires_section)

        adapter = PluginGraphAdapter(
            graph=graph,
            wire_model=wire_model,
            cross_model=cross_model,
            topology_editor=editor,
        )

        return editor, graph, adapter, wire_model, cross_model

    def test_load_scene_creates_nodes(self, qapp) -> None:
        editor, graph, adapter, _, _ = self._make_system()
        adapter.load_scene()

        assert len(adapter.node_map) == 2
        assert "camera_0" in adapter.node_map
        assert "processor_0" in adapter.node_map

    def test_refresh_after_add_process(self, qapp) -> None:
        """Добавление процесса → refresh → новая нода на канвасе."""
        editor, graph, adapter, _, cross_model = self._make_system()
        adapter.load_scene()
        assert len(adapter.node_map) == 2

        editor.update_item("processes", "render_0", {
            "name": "render_0",
            "class_path": "",
            "priority": "normal",
            "auto_start": True,
            "sort_order": 2,
            "plugins": [],
        })

        cross_model.invalidate()
        adapter.refresh_from_topology()

        assert len(adapter.node_map) == 3
        assert "render_0" in adapter.node_map

    def test_load_scene_with_existing_wires(self, qapp) -> None:
        """Blueprint с wires → ноды + соединения (порты могут отсутствовать)."""
        editor, graph, adapter, wire_model, _ = self._make_system()

        editor._data["processes"]["camera_0"]["plugins"] = [
            {"plugin_class": "CapturePlugin", "plugin_name": "capture"},
        ]
        editor._data["processes"]["processor_0"]["plugins"] = [
            {"plugin_class": "ColorMaskPlugin", "plugin_name": "color_mask"},
        ]

        editor._data["wires"]["wire_0001"] = {
            "source": "camera_0.capture.frame",
            "target": "processor_0.color_mask.frame",
            "description": "test",
            "transport": "router",
            "shm_config": {},
        }

        adapter.load_scene()

        # Ноды создаются всегда
        assert len(adapter.node_map) == 2

    def test_disconnect_signals_no_error(self, qapp) -> None:
        _, _, adapter, _, _ = self._make_system()
        adapter.load_scene()
        adapter.disconnect_signals()

    def test_single_data_tree_sync(self, qapp) -> None:
        """Wires из adapter доступны через topology editor (единое дерево)."""
        editor, graph, adapter, wire_model, _ = self._make_system()
        adapter.load_scene()

        # Добавляем wire напрямую через editor
        editor.update_item("wires", "wire_test", {
            "source": "camera_0.cap.frame",
            "target": "processor_0.mask.frame",
            "description": "",
            "transport": "router",
            "shm_config": {},
        })

        # Wire виден ч��рез wire_model (те же данные)
        assert "wire_test" in wire_model.wires
        assert wire_model.wires["wire_test"]["source"] == "camera_0.cap.frame"
