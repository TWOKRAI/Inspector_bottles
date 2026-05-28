"""Интеграционные тесты PipelineTab -- 3-панельный layout. Task E.1: AppServices."""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.pipeline.tab import PipelineTab
from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette import PluginPalette
from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector import NodeInspectorPanel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_view import GraphView

from ._helpers import make_pipeline_services


class TestPipelineTabCreate:
    def test_create(self, qtbot):
        """Tab создаётся без исключений."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_create_via_init(self, qtbot):
        """Tab создаётся через __init__."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        assert isinstance(tab, PipelineTab)


class TestPipelineTabLayout:
    def test_palette_exists(self, qtbot):
        """Палитра присутствует во 2-й колонке DiffScrollTabLayout."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        assert isinstance(tab._palette, PluginPalette)

    def test_graphview_exists(self, qtbot):
        """Canvas присутствует в content-колонке."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        assert isinstance(tab._view, GraphView)

    def test_inspector_exists(self, qtbot):
        """Inspector присутствует в content-колонке (под canvas)."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        assert isinstance(tab._inspector, NodeInspectorPanel)

    def test_content_splitter_has_two_panels(self, qtbot):
        """Content-колонка — вертикальный splitter с canvas (0) и inspector (1)."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        assert tab._content_splitter.count() == 2
        sizes = tab._content_splitter.sizes()
        assert len(sizes) == 2
        assert all(s >= 0 for s in sizes)

    def test_action_buttons_present(self, qtbot):
        """В action-колонке — 8 кнопок управления."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        for aid in ("delete", "auto_layout", "validate", "fit", "zoom_in", "zoom_out"):
            assert aid in tab._action_buttons


class TestPipelineTabScene:
    def test_scene_populated(self, qtbot):
        """Сцена содержит ноды и edges из topology."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        assert tab._scene.node_count() == 2
        assert tab._scene.edge_count() == 1

    def test_empty_topology(self, qtbot):
        """Пустая topology — сцена пуста."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        assert tab._scene.node_count() == 0
        assert tab._scene.edge_count() == 0


class TestPipelineTabToolbar:
    def test_toolbar_zoom_in(self, qtbot):
        """zoom_in не падает."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        old_zoom = tab._view._current_zoom
        tab._on_toolbar_action("zoom_in")
        assert tab._view._current_zoom >= old_zoom

    def test_toolbar_zoom_out(self, qtbot):
        """zoom_out не падает."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("zoom_out")

    def test_toolbar_fit(self, qtbot):
        """fit не падает."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("fit")

    def test_toolbar_validate(self, qtbot, monkeypatch):
        """validate не падает (QMessageBox патчится)."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)

        tab._on_toolbar_action("validate")

    def test_toolbar_validate_no_errors(self, qtbot, monkeypatch):
        """validate с пустой topology не показывает ошибок."""
        services = make_pipeline_services(topology={"processes": [], "wires": []})
        tab = PipelineTab(services)
        qtbot.addWidget(tab)

        shown_info = []

        from PySide6.QtWidgets import QMessageBox

        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: shown_info.append("info"))
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: shown_info.append("warning"))

        tab._on_toolbar_action("validate")
        assert "warning" not in shown_info

    def test_toolbar_auto_layout(self, qtbot):
        """auto_layout не падает."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("auto_layout")

    def test_toolbar_delete_no_selection(self, qtbot):
        """delete без выбора не падает."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("delete")


class TestPipelineTabInspector:
    def test_selection_shows_inspector(self, qtbot):
        """Выбор ноды через show_node заполняет инспектор."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)

        tab._inspector.show_node("camera", "source", plugins=[{"plugin_name": "capture"}])
        assert tab._inspector.current_process == "camera"

    def test_deselection_clears_inspector(self, qtbot):
        """Отмена выбора → placeholder (current_process пустой)."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)

        tab._inspector.show_node("camera", "source")
        tab._inspector.clear()

        assert tab._inspector.current_process == ""

    def test_on_selection_changed_empty(self, qtbot):
        """_on_selection_changed при пустом выборе не падает."""
        services = make_pipeline_services()
        tab = PipelineTab(services)
        qtbot.addWidget(tab)

        tab._on_selection_changed()
        assert tab._inspector.current_process == ""
