"""Тесты PipelinePresenter — обработчики target_process и display_id (Task 7a.3).
Task E.1: мигрировано на AppServices.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from multiprocess_prototype.frontend.widgets.tabs.pipeline.presenter import PipelinePresenter
from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector.inspector_panel import (
    NodeInspectorPanel,
)

from ._helpers import make_pipeline_services


# ------------------------------------------------------------------ #
#  Фикстуры                                                           #
# ------------------------------------------------------------------ #


def _make_services_for_presenter(topology=None, display_registry=None):
    """Создать AppServices для PipelinePresenter с опциональным display_registry."""
    topo = topology or {
        "processes": [
            {"process_name": "p1", "plugins": [{"plugin_name": "capture"}]},
            {"process_name": "p2", "plugins": [{"plugin_name": "color_mask"}]},
        ],
        "wires": [],
        "displays": [
            {"node_id": "disp1", "display_id": "main_output", "display_name": "Основной"},
        ],
    }

    # Если передан display_registry — создаём services с custom displays
    if display_registry is not None:
        from multiprocess_prototype.domain.tests.conftest import make_test_app_services
        from multiprocess_prototype.domain.tests._fakes import FakeConfigStore

        config = FakeConfigStore(initial={"topology": topo})

        # Создаём mock DisplayCatalog с resolve поддержкой
        displays = MagicMock()

        # Простой маппинг: если display_registry.get() возвращает entry с .name
        def _resolve(did):
            entry = display_registry.get(did)
            if entry is not None:
                from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec

                return DisplaySpec(display_id=did, display_name=getattr(entry, "name", ""))
            return None

        displays.resolve.side_effect = _resolve
        displays.list_displays.return_value = ()

        return make_test_app_services(config=config, displays=displays)

    return make_pipeline_services(topology=topo)


def _make_display_entry(display_id: str, name: str):
    """Создать mock DisplayEntry."""
    entry = MagicMock()
    entry.id = display_id
    entry.name = name
    return entry


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


class TestPresenterDisplayIdChanged:
    def test_display_id_change_updates_model(self):
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        presenter._on_display_id_changed("disp1", "secondary")

        topo = presenter.model.to_topology_dict()
        disp1 = next(
            (d for d in topo.get("displays", []) if d.get("node_id") == "disp1"),
            None,
        )
        assert disp1 is not None
        assert disp1.get("display_id") == "secondary"

    def test_display_id_change_updates_display_name_from_registry(self):
        entries = [_make_display_entry("secondary", "Вторичный дисплей")]
        registry_mock = MagicMock()
        registry_mock.get.side_effect = lambda did: next((e for e in entries if e.id == did), None)

        services = _make_services_for_presenter(display_registry=registry_mock)
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        presenter._on_display_id_changed("disp1", "secondary")

        topo = presenter.model.to_topology_dict()
        disp1 = next(
            (d for d in topo.get("displays", []) if d.get("node_id") == "disp1"),
            None,
        )
        assert disp1 is not None
        assert disp1.get("display_id") == "secondary"
        assert disp1.get("display_name") == "Вторичный дисплей"

    def test_display_id_change_nonexistent_node_logs_warning(self, caplog):
        import logging

        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        with caplog.at_level(logging.WARNING):
            presenter._on_display_id_changed("nonexistent_disp", "main")

        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_display_id_suppressed_when_suppress_flag_set(self):
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        presenter._suppress = True
        presenter._on_display_id_changed("disp1", "new_display")

        topo = presenter.model.to_topology_dict()
        disp1 = next(
            (d for d in topo.get("displays", []) if d.get("node_id") == "disp1"),
            None,
        )
        assert disp1.get("display_id") == "main_output"


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
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)
        presenter.load_topology_from_config()

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        panel.display_id_changed.emit("disp1", "new_display")

        topo = presenter.model.to_topology_dict()
        disp1 = next(
            (d for d in topo.get("displays", []) if d.get("node_id") == "disp1"),
            None,
        )
        assert disp1 is not None
        assert disp1.get("display_id") == "new_display"

    def test_set_inspector_passes_services_to_panel(self, qtbot):
        services = _make_services_for_presenter()
        presenter = PipelinePresenter(services)

        panel = NodeInspectorPanel()
        qtbot.addWidget(panel)
        presenter.set_inspector(panel)

        assert panel._services is services
