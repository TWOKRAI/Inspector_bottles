# -*- coding: utf-8 -*-
"""Тесты G.6 (UX): auto-reveal, validation-feedback, selection-persist, diff-view.

Используют реальный CommandDispatcherOrchestrator + EventBus (не MagicMock),
чтобы проверять полную цепочку dispatch → events → реакция UI.

Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md (Wave 7, G.6.1–G.6.4)
"""

from __future__ import annotations

from multiprocess_prototype.domain.protocols.plugin_catalog import PluginSpec, PortSpec
from multiprocess_prototype.frontend.widgets.tabs.pipeline.diff import TopologyDiff, topology_diff
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_scene import GraphScene
from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from multiprocess_prototype.frontend.widgets.tabs.pipeline.tab import PipelineTab

from ._helpers import make_pipeline_services, make_pipeline_services_with_orchestrator

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

# Топология с двумя процессами a→b (для cycle / selection тестов)
_TWO_PROC = {
    "processes": [
        {"process_name": "a", "plugins": [{"plugin_name": "capture"}]},
        {"process_name": "b", "plugins": [{"plugin_name": "blur"}]},
    ],
    "wires": [{"source": "a.capture.frame", "target": "b.blur.frame"}],
}


# ===========================================================================
# G.6.1 — Auto-reveal новых нод
# ===========================================================================


class TestAutoReveal:
    def test_reveal_called_on_process_added(self, qtbot, monkeypatch):
        """dispatch(AddProcess) → ProcessAdded → tab центрирует новую ноду."""
        services = make_pipeline_services_with_orchestrator(
            topology={"processes": [], "wires": []},
            plugin_specs=_PLUGIN_SPECS,
        )
        tab = PipelineTab(services)
        qtbot.addWidget(tab)

        revealed: list = []
        monkeypatch.setattr(tab._view, "reveal_node", revealed.append)

        tab._presenter.add_process_from_plugin("capture")

        assert len(revealed) == 1
        assert revealed[0] is tab._scene.get_node("capture")

    def test_no_reveal_on_undo(self, qtbot, monkeypatch):
        """undo НЕ переигрывает ProcessAdded → reveal не вызывается на undo."""
        services = make_pipeline_services_with_orchestrator(
            topology={"processes": [], "wires": []},
            plugin_specs=_PLUGIN_SPECS,
        )
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        tab._presenter.add_process_from_plugin("capture")

        revealed: list = []
        monkeypatch.setattr(tab._view, "reveal_node", revealed.append)

        services.commands.undo()
        services.commands.redo()

        assert revealed == []

    def test_reveal_node_view_method(self, qtbot):
        """GraphView.reveal_node не падает на None и на реальном item."""
        scene = GraphScene()
        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_view import GraphView

        view = GraphView(scene)
        qtbot.addWidget(view)
        view.reveal_node(None)  # no-op без исключения

        from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.node_item import NodeData

        item = scene.add_node(NodeData(node_id="n", title="n", subtitle="x", category="x"))
        view.reveal_node(item)  # не падает


# ===========================================================================
# G.6.2 — Validation-feedback (DomainError → notify)
# ===========================================================================


class TestValidationFeedback:
    def test_cycle_reported_to_notify(self):
        """ConnectWire-цикл отклонён → notify получает сообщение."""
        services = make_pipeline_services_with_orchestrator(topology=_TWO_PROC, plugin_specs=_PLUGIN_SPECS)
        messages: list[str] = []
        p = PipelinePresenter(services, notify=messages.append)
        p.load_topology_from_config()

        ok = p.add_wire("b.blur.out", "a.capture.frame")  # b→a = цикл
        assert ok is False
        assert len(messages) == 1
        assert "отклонено" in messages[0].lower()

    def test_notify_none_no_crash(self):
        """notify=None (default) → отклонённая мутация не падает (только лог)."""
        services = make_pipeline_services_with_orchestrator(topology=_TWO_PROC, plugin_specs=_PLUGIN_SPECS)
        p = PipelinePresenter(services)  # notify не задан
        p.load_topology_from_config()
        assert p.add_wire("b.blur.out", "a.capture.frame") is False

    def test_field_set_error_reported(self):
        """SetPluginConfig на несуществующий процесс → notify."""
        services = make_pipeline_services_with_orchestrator(topology=_TWO_PROC, plugin_specs=_PLUGIN_SPECS)
        messages: list[str] = []
        p = PipelinePresenter(services, notify=messages.append)
        p.load_topology_from_config()

        p._on_inspector_field_changed("ghost-process", "threshold", 42)
        assert len(messages) == 1


# ===========================================================================
# G.6.3 — Selection-persist через scene reload
# ===========================================================================


class TestSelectionPersist:
    def _make(self, qtbot):
        services = make_pipeline_services_with_orchestrator(topology=_TWO_PROC, plugin_specs=_PLUGIN_SPECS)
        p = PipelinePresenter(services)
        scene = GraphScene()
        p.set_scene(scene)
        nodes, edges = p.load_topology_from_config()
        p.load_scene_with_ports(nodes, edges)
        return services, p, scene

    def test_selection_survives_reload(self, qtbot):
        """Выделение ноды сохраняется через reload (dispatch с TopologyReplaced)."""
        services, p, scene = self._make(qtbot)
        scene.get_node("a").setSelected(True)
        assert scene.get_node("a").isSelected()

        # add_process триггерит TopologyReplaced → full reload
        p.add_process_from_plugin("color_mask")

        node_a = scene.get_node("a")
        assert node_a is not None
        assert node_a.isSelected()

    def test_selection_survives_undo(self, qtbot):
        """Выделение сохраняется через undo/redo."""
        services, p, scene = self._make(qtbot)
        scene.get_node("b").setSelected(True)
        p.add_process_from_plugin("color_mask")

        services.commands.undo()
        node_b = scene.get_node("b")
        assert node_b is not None
        assert node_b.isSelected()

    def test_removed_node_selection_graceful(self, qtbot):
        """Выделенная нода удалена → restore graceful (нода отсутствует, нет падения)."""
        services, p, scene = self._make(qtbot)
        scene.get_node("a").setSelected(True)

        p.remove_selected(["a"])  # a удалён каскадом
        assert scene.get_node("a") is None  # без исключения


# ===========================================================================
# G.6.4 — Diff-view: topology_diff (pure) + compute_active_recipe_diff
# ===========================================================================


class TestTopologyDiff:
    def test_empty_when_equal(self):
        topo = {
            "processes": [{"process_name": "a", "plugins": [{"plugin_name": "capture", "config": {}}]}],
            "wires": [],
            "displays": [],
        }
        d = topology_diff(topo, dict(topo))
        assert d.is_empty
        assert d.summary() == []

    def test_process_added(self):
        cur = {"processes": [{"process_name": "a"}, {"process_name": "b"}], "wires": []}
        sav = {"processes": [{"process_name": "a"}], "wires": []}
        d = topology_diff(cur, sav)
        assert d.processes_added == ["b"]
        assert d.processes_removed == []
        assert not d.is_empty

    def test_process_removed(self):
        cur = {"processes": [{"process_name": "a"}], "wires": []}
        sav = {"processes": [{"process_name": "a"}, {"process_name": "b"}], "wires": []}
        d = topology_diff(cur, sav)
        assert d.processes_removed == ["b"]

    def test_process_config_changed(self):
        cur = {"processes": [{"process_name": "a", "plugins": [{"plugin_name": "x", "config": {"v": 1}}]}]}
        sav = {"processes": [{"process_name": "a", "plugins": [{"plugin_name": "x", "config": {"v": 2}}]}]}
        d = topology_diff(cur, sav)
        assert d.processes_changed == ["a"]
        assert d.processes_added == []

    def test_wire_added_removed(self):
        cur = {"processes": [], "wires": [{"source": "a.p.o", "target": "b.p.i"}]}
        sav = {"processes": [], "wires": [{"source": "c.p.o", "target": "d.p.i"}]}
        d = topology_diff(cur, sav)
        assert ("a.p.o", "b.p.i") in d.wires_added
        assert ("c.p.o", "d.p.i") in d.wires_removed

    def test_display_added_removed(self):
        cur = {"processes": [], "displays": [{"node_id": "a.p.o", "display_id": "main"}]}
        sav = {"processes": [], "displays": [{"node_id": "a.p.o", "display_id": "preview"}]}
        d = topology_diff(cur, sav)
        assert ("a.p.o", "main") in d.displays_added
        assert ("a.p.o", "preview") in d.displays_removed

    def test_metadata_ignored(self):
        """gui_positions/metadata не дают ложного diff."""
        cur = {"processes": [{"process_name": "a"}], "metadata": {"gui_positions": {"a": [1, 2]}}}
        sav = {"processes": [{"process_name": "a"}], "metadata": {"gui_positions": {"a": [99, 99]}}}
        d = topology_diff(cur, sav)
        assert d.is_empty

    def test_summary_nonempty(self):
        d = TopologyDiff(processes_added=["x"], wires_added=[("s", "t")])
        lines = d.summary()
        assert any("x" in ln for ln in lines)
        assert any("s" in ln and "t" in ln for ln in lines)


class TestComputeActiveRecipeDiff:
    def test_none_when_no_active_recipe(self):
        services = make_pipeline_services()
        p = PipelinePresenter(services)
        assert p.compute_active_recipe_diff() is None

    def test_diff_vs_active_recipe(self):
        # current editor-топология (default _helpers: camera + processor + wire)
        services = make_pipeline_services()
        # Активный рецепт с другим blueprint (только camera, без processor)
        services.recipes._raw["r1"] = {
            "blueprint": {
                "processes": [{"process_name": "camera", "plugins": [{"plugin_name": "capture"}]}],
                "wires": [],
            }
        }
        services.recipes._active = "r1"

        p = PipelinePresenter(services)
        diff = p.compute_active_recipe_diff()
        assert diff is not None
        # processor есть в editor, нет в рецепте → added; wire тоже added
        assert "processor" in diff.processes_added
        assert not diff.is_empty
