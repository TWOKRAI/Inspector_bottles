# -*- coding: utf-8 -*-
"""Тесты G.4.2: process-мутации Pipeline через domain dispatch + undo/redo.

Используют реальный CommandDispatcherOrchestrator + TopologyRepositoryStore +
EventBus (не MagicMock). Проверяют полную цепочку:
  dispatch → Project.apply → store.save → TopologyReplaced → presenter reload.

Покрытие:
  - add_process_from_plugin → процесс в repo (персист) + нода в scene + порты
  - remove_selected([proc]) → процесс удалён из repo + каскад wires
  - add_wire(proc→proc) → wire в repo; цикл → return False; дубликат → return False
  - undo/redo через services.commands (round-trip на реальном store)
  - РЕГРЕССИЯ: display-ветка remove + wire-to-display на legacy пути (не сломана)

Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md (Task G.4.2)
"""

from __future__ import annotations

from multiprocess_prototype.domain.protocols.plugin_catalog import PluginSpec, PortSpec
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter

from ._helpers import make_pipeline_services_with_orchestrator


# ---------------------------------------------------------------------------
# Общие фикстуры
# ---------------------------------------------------------------------------

_PLUGIN_SPECS = {
    "capture": PluginSpec(
        name="capture",
        category="source",
        ports=(PortSpec(name="frame", dtype="image/bgr", direction="output"),),
    ),
    "color_mask": PluginSpec(
        name="color_mask",
        category="filter",
        ports=(
            PortSpec(name="frame", dtype="image/bgr", direction="input"),
            PortSpec(name="mask", dtype="image/gray", direction="output"),
        ),
    ),
    "blur": PluginSpec(
        name="blur",
        category="filter",
        ports=(
            PortSpec(name="frame", dtype="image/bgr", direction="input"),
            PortSpec(name="out", dtype="image/bgr", direction="output"),
        ),
    ),
}


def _make_orchestrator_services(topology: dict | None = None):
    """Создать services с реальным orchestrator и plugin_specs для wire-валидации."""
    return make_pipeline_services_with_orchestrator(
        topology=topology,
        plugin_specs=_PLUGIN_SPECS,
    )


# ===========================================================================
# add_process_from_plugin — dispatch(AddProcess)
# ===========================================================================


class TestAddProcessDomainDispatch:
    """add_process_from_plugin через domain dispatch."""

    def test_process_persisted_in_repo(self):
        """После add_process_from_plugin процесс есть в services.topology.load()."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        name = p.add_process_from_plugin("capture", x=100.0, y=200.0)
        assert name == "capture"

        # Проверка persist — топология в repo содержит процесс
        topo = services.topology.load().to_dict()
        proc_names = [proc["process_name"] for proc in topo.get("processes", []) if isinstance(proc, dict)]
        assert "capture" in proc_names

    def test_process_in_model_after_reload(self):
        """После dispatch модель presenter'а содержит процесс (через TopologyReplaced reload)."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_process_from_plugin("capture")
        assert "capture" in p.model.get_process_names()

    def test_process_node_in_scene_after_dispatch(self, qtbot):
        """Нода появляется в scene после dispatch (через TopologyReplaced → full reload)."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        scene = GraphScene()
        # QApplication уже создан pytest-qt
        p.set_scene(scene)
        p.load_topology_from_config()

        p.add_process_from_plugin("capture", x=50.0, y=60.0)
        assert scene.node_count() == 1
        node = scene.get_node("capture")
        assert node is not None

    def test_port_schemas_on_node_after_dispatch(self, qtbot):
        """Ноды имеют корректные port_schemas после dispatch (находка #7 аудита)."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        scene = GraphScene()
        # QApplication уже создан pytest-qt (addWidget не нужен для GraphScene)
        p.set_scene(scene)
        p.load_topology_from_config()

        p.add_process_from_plugin("color_mask")
        node = scene.get_node("color-mask")
        assert node is not None
        # NodeItem хранит порты — проверяем что их ≥ 2 (input + output)
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.port_item import PortItem

        port_items = [child for child in node.childItems() if isinstance(child, PortItem)]
        assert len(port_items) >= 2, f"Ожидалось ≥2 портов, найдено {len(port_items)}"

    def test_unique_name_increments(self):
        """Дубликат имени → автоинкремент (как прежде)."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        name1 = p.add_process_from_plugin("blur")
        name2 = p.add_process_from_plugin("blur")
        assert name1 == "blur"
        assert name2 == "blur_1"
        assert len(p.model.get_process_names()) == 2

    def test_add_process_carries_plugin(self):
        """AddProcess обязан нести плагин (иначе нода пустая)."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_process_from_plugin("capture")
        topo = services.topology.load().to_dict()
        proc = topo["processes"][0]
        assert len(proc.get("plugins", [])) >= 1
        plugin = proc["plugins"][0]
        assert plugin.get("plugin_name") == "capture"


# ===========================================================================
# remove_selected — dispatch(RemoveProcess) для process-нод
# ===========================================================================


class TestRemoveSelectedDomainDispatch:
    """remove_selected (process-ветка) через domain dispatch."""

    def test_process_removed_from_repo(self):
        """После remove_selected процесс удалён из repo (fix desync-бага)."""
        services = _make_orchestrator_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["camera"])
        topo = services.topology.load().to_dict()
        proc_names = [proc["process_name"] for proc in topo.get("processes", []) if isinstance(proc, dict)]
        assert "camera" not in proc_names
        assert "processor" in proc_names

    def test_wire_cascade_on_remove(self):
        """Domain каскадно удаляет wires при удалении процесса."""
        services = _make_orchestrator_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        # Исходно: camera→processor wire
        assert len(p.model.get_wires()) == 1

        p.remove_selected(["camera"])
        # Wire каскадно удалён
        assert len(p.model.get_wires()) == 0

    def test_scene_updated_after_remove(self, qtbot):
        """Scene обновляется после remove (через TopologyReplaced)."""
        services = _make_orchestrator_services()
        p = PipelinePresenter(services)
        scene = GraphScene()
        # QApplication уже создан pytest-qt (addWidget не нужен для GraphScene)
        p.set_scene(scene)
        p.load_topology_from_config()
        p.load_scene_with_ports(*p._topology_to_graph(services.topology.load().to_dict()))

        assert scene.node_count() == 2
        p.remove_selected(["camera"])
        assert scene.node_count() == 1


# ===========================================================================
# add_wire — dispatch(ConnectWire) для process→process
# ===========================================================================


class TestAddWireDomainDispatch:
    """add_wire (process→process) через domain dispatch."""

    def test_wire_persisted_in_repo(self):
        """Wire сохраняется в repo через dispatch."""
        services = _make_orchestrator_services(
            topology={
                "processes": [
                    {"process_name": "a", "plugins": [{"plugin_name": "capture"}]},
                    {"process_name": "b", "plugins": [{"plugin_name": "blur"}]},
                ],
                "wires": [],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        result = p.add_wire("a.capture.frame", "b.blur.frame")
        assert result is True

        # Wire в repo
        topo = services.topology.load().to_dict()
        wires = topo.get("wires", [])
        assert len(wires) == 1

    def test_cycle_rejected(self):
        """Цикл → return False, repo не изменён (DomainError)."""
        services = _make_orchestrator_services(
            topology={
                "processes": [
                    {"process_name": "a", "plugins": [{"plugin_name": "capture"}]},
                    {"process_name": "b", "plugins": [{"plugin_name": "blur"}]},
                ],
                "wires": [
                    {"source": "a.capture.frame", "target": "b.blur.frame"},
                ],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        # b→a создаёт цикл
        result = p.add_wire("b.blur.out", "a.capture.frame")
        assert result is False
        # repo не изменён
        assert len(p.model.get_wires()) == 1

    def test_duplicate_rejected(self):
        """Дубликат wire → return False (presenter-guard, находка #5)."""
        services = _make_orchestrator_services(
            topology={
                "processes": [
                    {"process_name": "a", "plugins": [{"plugin_name": "capture"}]},
                    {"process_name": "b", "plugins": [{"plugin_name": "blur"}]},
                ],
                "wires": [
                    {"source": "a.capture.frame", "target": "b.blur.frame"},
                ],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        # Точная копия уже существующего wire
        result = p.add_wire("a.capture.frame", "b.blur.frame")
        assert result is False


# ===========================================================================
# remove_wire — dispatch(DisconnectWire / UnbindDisplay) — паритет со старым
# topology-редактором (удаление одного провода из контекст-меню edge)
# ===========================================================================


class TestRemoveWireDomainDispatch:
    """remove_wire через domain dispatch: process-wire и display-unbind."""

    def _two_proc_one_wire(self):
        return _make_orchestrator_services(
            topology={
                "processes": [
                    {"process_name": "a", "plugins": [{"plugin_name": "capture"}]},
                    {"process_name": "b", "plugins": [{"plugin_name": "blur"}]},
                ],
                "wires": [{"source": "a.capture.frame", "target": "b.blur.frame"}],
            }
        )

    def test_process_wire_removed_from_repo(self):
        """remove_wire(proc→proc) → DisconnectWire → wire снят из repo и модели."""
        services = self._two_proc_one_wire()
        p = PipelinePresenter(services)
        p.load_topology_from_config()
        assert len(p.model.get_wires()) == 1

        assert p.remove_wire("a.capture.frame", "b.blur.frame") is True
        assert len(p.model.get_wires()) == 0
        assert services.topology.load().to_dict().get("wires", []) == []

    def test_remove_wire_undo_restores(self):
        """undo после remove_wire → провод восстановлен."""
        services = self._two_proc_one_wire()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_wire("a.capture.frame", "b.blur.frame")
        assert len(p.model.get_wires()) == 0
        services.commands.undo()
        assert len(p.model.get_wires()) == 1

    def test_remove_wire_display_target_unbinds(self):
        """remove_wire(source → display.<id>.frame) → UnbindDisplay → привязка снята."""
        services = _make_display_services(
            topology={
                "processes": [{"process_name": "cam", "plugins": [{"plugin_name": "capture"}]}],
                "wires": [],
                "displays": [{"node_id": "cam.capture.frame", "display_id": "main"}],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()
        assert len(p.model.get_displays()) == 1

        assert p.remove_wire("cam.capture.frame", "display.main.frame") is True
        assert len(p.model.get_displays()) == 0


# ===========================================================================
# undo / redo — services.commands.undo() / redo()
# ===========================================================================


class TestUndoRedo:
    """Undo/redo через services.commands (round-trip на реальном store)."""

    def test_undo_restores_previous_state(self):
        """undo() восстанавливает состояние до dispatch."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_process_from_plugin("capture")
        assert "capture" in p.model.get_process_names()

        result = services.commands.undo()
        assert result is True
        assert "capture" not in p.model.get_process_names()

    def test_redo_reapplies_command(self):
        """redo() повторяет отменённую команду."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_process_from_plugin("capture")
        services.commands.undo()
        assert "capture" not in p.model.get_process_names()

        result = services.commands.redo()
        assert result is True
        assert "capture" in p.model.get_process_names()

    def test_undo_empty_stack_noop(self):
        """undo() на пустом стеке → no-op, False."""
        services = _make_orchestrator_services(topology={"processes": [], "wires": []})
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        result = services.commands.undo()
        assert result is False

    def test_undo_remove_restores_process(self):
        """undo после remove → процесс и wire восстановлены."""
        services = _make_orchestrator_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.remove_selected(["camera"])
        assert "camera" not in p.model.get_process_names()
        assert len(p.model.get_wires()) == 0

        services.commands.undo()
        assert "camera" in p.model.get_process_names()
        assert len(p.model.get_wires()) == 1

    def test_undo_wire_removes_wire(self):
        """undo после add_wire → wire удалён."""
        services = _make_orchestrator_services(
            topology={
                "processes": [
                    {"process_name": "a", "plugins": [{"plugin_name": "capture"}]},
                    {"process_name": "b", "plugins": [{"plugin_name": "blur"}]},
                ],
                "wires": [],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_wire("a.capture.frame", "b.blur.frame")
        assert len(p.model.get_wires()) == 1

        services.commands.undo()
        assert len(p.model.get_wires()) == 0


# ===========================================================================
# G.4.2b: display = binding — output→box через dispatch(BindDisplay/UnbindDisplay)
# ===========================================================================


def _make_display_services(topology: dict | None = None):
    """Services с orchestrator + каналами main/preview для BindDisplay-валидации."""
    return make_pipeline_services_with_orchestrator(
        topology=topology
        or {
            "processes": [{"process_name": "cam", "plugins": [{"plugin_name": "capture"}]}],
            "wires": [],
            "displays": [],
        },
        plugin_specs=_PLUGIN_SPECS,
        display_ids={"main", "preview"},
    )


class TestDisplayBindingDispatch:
    """output→display-бокс = dispatch(BindDisplay); удаление = dispatch(UnbindDisplay)."""

    def test_bind_via_add_wire_persists(self):
        """add_wire(source → display.<id>.frame) → BindDisplay → привязка в repo."""
        services = _make_display_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        ok = p.add_wire("cam.capture.frame", "display.main.frame")
        assert ok is True

        displays = services.topology.load().to_dict().get("displays", [])
        assert len(displays) == 1
        assert displays[0]["node_id"] == "cam.capture.frame"
        assert displays[0]["display_id"] == "main"

    def test_remove_box_unbinds(self):
        """remove_selected([display_id-бокс]) → UnbindDisplay → привязка снята."""
        services = _make_display_services(
            topology={
                "processes": [{"process_name": "cam", "plugins": [{"plugin_name": "capture"}]}],
                "wires": [],
                "displays": [{"node_id": "cam.capture.frame", "display_id": "main"}],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()
        assert len(p.model.get_displays()) == 1

        p.remove_selected(["main"])  # id бокса = display_id канала
        assert len(p.model.get_displays()) == 0

    def test_bind_undo(self):
        """undo после BindDisplay → привязка удалена (snapshot-undo)."""
        services = _make_display_services()
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        p.add_wire("cam.capture.frame", "display.main.frame")
        assert len(p.model.get_displays()) == 1

        services.commands.undo()
        assert len(p.model.get_displays()) == 0

    def test_fan_in_two_sources_one_channel(self):
        """Fan-in: два выхода → один канал = две привязки."""
        services = _make_display_services(
            topology={
                "processes": [
                    {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
                    {"process_name": "b", "plugins": [{"plugin_name": "blur"}]},
                ],
                "wires": [],
                "displays": [],
            }
        )
        p = PipelinePresenter(services)
        p.load_topology_from_config()

        assert p.add_wire("cam.capture.frame", "display.main.frame") is True
        assert p.add_wire("b.blur.out", "display.main.frame") is True
        assert len(p.model.get_displays()) == 2


class TestDisplaySceneRendering:
    """G.4.2b: display-боксы и binding-рёбра рендерятся из topo["displays"]."""

    def _render(self, displays: list[dict], qtbot):
        """Построить services + scene и отрисовать topology с привязками."""
        services = _make_display_services(
            topology={
                "processes": [
                    {"process_name": "cam", "plugins": [{"plugin_name": "capture"}]},
                    {"process_name": "b", "plugins": [{"plugin_name": "blur"}]},
                ],
                "wires": [],
                "displays": displays,
            }
        )
        p = PipelinePresenter(services)
        scene = GraphScene()
        p.set_scene(scene)
        nodes, edges = p.load_topology_from_config()
        p.load_scene_with_ports(nodes, edges)
        return scene

    def test_display_box_rendered_on_load(self, qtbot):
        """Бокс DisplayNodeItem появляется на scene из topo["displays"]."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.display_node_item import (
            DisplayNodeItem,
        )

        scene = self._render([{"node_id": "cam.capture.frame", "display_id": "main"}], qtbot)
        box = scene.get_node("main")
        assert isinstance(box, DisplayNodeItem)

    def test_binding_edge_source_to_box(self, qtbot):
        """Binding-ребро source-процесс → бокс присутствует."""
        scene = self._render([{"node_id": "cam.capture.frame", "display_id": "main"}], qtbot)
        # cam-нода + бокс main = 1 ребро между ними
        assert scene.edge_count() == 1

    def test_fan_in_one_box_two_edges(self, qtbot):
        """Fan-in: 2 источника → 1 бокс, 2 ребра."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.display_node_item import (
            DisplayNodeItem,
        )

        scene = self._render(
            [
                {"node_id": "cam.capture.frame", "display_id": "main"},
                {"node_id": "b.blur.out", "display_id": "main"},
            ],
            qtbot,
        )
        assert isinstance(scene.get_node("main"), DisplayNodeItem)
        assert scene.get_node("preview") is None
        assert scene.edge_count() == 2

    def test_fan_out_two_boxes(self, qtbot):
        """Fan-out: 1 источник → 2 канала = 2 бокса, 2 ребра."""
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.display_node_item import (
            DisplayNodeItem,
        )

        scene = self._render(
            [
                {"node_id": "cam.capture.frame", "display_id": "main"},
                {"node_id": "cam.capture.frame", "display_id": "preview"},
            ],
            qtbot,
        )
        assert isinstance(scene.get_node("main"), DisplayNodeItem)
        assert isinstance(scene.get_node("preview"), DisplayNodeItem)
        assert scene.edge_count() == 2
