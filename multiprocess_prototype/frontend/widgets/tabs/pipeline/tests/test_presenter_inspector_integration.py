"""Тесты PipelinePresenter — обработчики target_process и display_id (Task 7a.3).
Task E.1: мигрировано на AppServices.
"""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.inspector_panel import (
    NodeInspectorPanel,
)

from ._helpers import make_pipeline_services, make_pipeline_services_with_orchestrator


# ------------------------------------------------------------------ #
#  Фикстуры                                                           #
# ------------------------------------------------------------------ #


def _make_services_for_presenter(topology=None):
    """Создать AppServices для PipelinePresenter (target_process тесты).

    G.4.2b: display = binding, node_id привязки — source endpoint выхода.
    """
    topo = topology or {
        "processes": [
            {"process_name": "p1", "plugins": [{"plugin_name": "capture"}]},
            {"process_name": "p2", "plugins": [{"plugin_name": "color_mask"}]},
        ],
        "wires": [],
        "displays": [
            {"node_id": "p2.color_mask.frame", "display_id": "main_output"},
        ],
    }
    return make_pipeline_services(topology=topo)


# ------------------------------------------------------------------ #
#  Тесты: _on_target_process_changed                                  #
# ------------------------------------------------------------------ #


class TestPresenterTargetProcessChanged:
    def test_target_process_change_updates_model(self):
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)

        presenter.load_topology_from_config()
        presenter._on_target_process_changed("p1", "p2")

        topo = presenter.model.to_topology_dict()
        processes = topo.get("processes", [])
        p1 = next((p for p in processes if p.get("process_name") == "p1"), None)
        assert p1 is not None
        assert p1.get("target_process") == "p2"

    def test_target_process_can_point_to_existing_process(self):
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        presenter._on_target_process_changed("p1", "p2")

        topo = presenter.model.to_topology_dict()
        p1 = next((p for p in topo["processes"] if p.get("process_name") == "p1"), None)
        assert p1 is not None
        assert p1.get("target_process") == "p2"

    def test_target_process_change_nonexistent_node_logs_warning(self, caplog):
        import logging

        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        with caplog.at_level(logging.WARNING):
            presenter._on_target_process_changed("nonexistent_node", "p2")

        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_target_process_suppressed_when_suppress_flag_set(self):
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        presenter._suppress = True
        presenter._on_target_process_changed("p1", "new_name")

        topo = presenter.model.to_topology_dict()
        p1 = next((p for p in topo["processes"] if p.get("process_name") == "p1"), None)
        assert p1.get("target_process", None) is None


# ------------------------------------------------------------------ #
#  Тесты: _on_display_id_changed                                      #
# ------------------------------------------------------------------ #


def _make_orch_services_with_binding(channels=frozenset({"main_output", "secondary"})):
    """Orchestrator-services с одной display-привязкой p2.color_mask.frame→main_output.

    G.4.2b: смена канала бокса = ребиндинг через domain dispatch, поэтому нужен
    реальный orchestrator (FakeCommandDispatcher — no-op). channels — валидные каналы
    для BindDisplay-валидации.
    """
    return make_pipeline_services_with_orchestrator(
        topology={
            "processes": [{"process_name": "p2", "plugins": [{"plugin_name": "color_mask"}]}],
            "wires": [],
            "displays": [{"node_id": "p2.color_mask.frame", "display_id": "main_output"}],
        },
        display_ids=set(channels),
    )


class TestPresenterDisplayIdChanged:
    """G.4.2b: _on_display_id_changed ребиндит привязки бокса через dispatch."""

    def test_display_id_change_rebinds_to_new_channel(self):
        services = _make_orch_services_with_binding()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        # id бокса = текущий display_id канала
        presenter._on_display_id_changed("main_output", "secondary")

        displays = presenter.model.get_displays()
        assert len(displays) == 1
        assert displays[0]["display_id"] == "secondary"
        assert displays[0]["node_id"] == "p2.color_mask.frame"

    def test_display_id_change_noop_when_same(self):
        services = _make_orch_services_with_binding()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        presenter._on_display_id_changed("main_output", "main_output")

        assert presenter.model.get_displays()[0]["display_id"] == "main_output"

    def test_display_id_rebind_single_undo(self):
        """coalesce_key: один undo отменяет ребиндинг целиком (Unbind+Bind)."""
        services = _make_orch_services_with_binding()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        presenter._on_display_id_changed("main_output", "secondary")
        assert presenter.model.get_displays()[0]["display_id"] == "secondary"

        # Один Ctrl+Z возвращает к исходному каналу
        assert services.commands.undo() is True
        displays = presenter.model.get_displays()
        assert len(displays) == 1
        assert displays[0]["display_id"] == "main_output"
        assert services.commands.can_undo() is False

    def test_display_id_change_nonexistent_box_logs_warning(self, caplog):
        import logging

        services = _make_orch_services_with_binding()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        with caplog.at_level(logging.WARNING):
            presenter._on_display_id_changed("nonexistent_channel", "secondary")

        assert any(r.levelno >= logging.WARNING for r in caplog.records)
        # Привязка не тронута
        assert presenter.model.get_displays()[0]["display_id"] == "main_output"

    def test_display_id_suppressed_when_suppress_flag_set(self):
        services = _make_orch_services_with_binding()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        presenter._suppress = True
        presenter._on_display_id_changed("main_output", "secondary")

        assert presenter.model.get_displays()[0]["display_id"] == "main_output"


# ------------------------------------------------------------------ #
#  Тесты: set_inspector подключает сигналы                            #
# ------------------------------------------------------------------ #


class TestPresenterSetInspectorSignals:
    def test_set_inspector_connects_target_process_signal(self, qtbot):
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        panel.target_process_changed.emit("p1", "p2")

        topo = presenter.model.to_topology_dict()
        p1 = next((p for p in topo["processes"] if p.get("process_name") == "p1"), None)
        assert p1 is not None

    def test_set_inspector_connects_display_id_signal(self, qtbot):
        services = _make_orch_services_with_binding()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        # G.4.2b: сигнал несёт (id бокса = текущий канал, новый канал)
        panel.display_id_changed.emit("main_output", "secondary")

        displays = presenter.model.get_displays()
        assert len(displays) == 1
        assert displays[0]["display_id"] == "secondary"

    def test_set_inspector_passes_services_to_panel(self, qtbot):
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        assert panel._services is services
