"""Интеграционные тесты PipelineTab -- 3-панельный layout."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from multiprocess_prototype.frontend.widgets.tabs.pipeline.tab import PipelineTab
from multiprocess_prototype.frontend.widgets.tabs.pipeline.palette import PluginPalette
from multiprocess_prototype.frontend.widgets.tabs.pipeline.inspector import NodeInspectorPanel
from multiprocess_prototype.frontend.widgets.tabs.pipeline.graph.graph_view import GraphView


def _make_full_ctx(topology=None):
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


class TestPipelineTabCreate:
    def test_create(self, qtbot):
        """Tab создаётся без исключений."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_create_via_init(self, qtbot):
        """Tab создаётся через __init__."""
        ctx = _make_full_ctx()
        tab = PipelineTab(ctx)
        qtbot.addWidget(tab)
        assert isinstance(tab, PipelineTab)


class TestPipelineTabLayout:
    def test_has_three_panels(self, qtbot):
        """Splitter содержит ровно 3 виджета."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab._splitter.count() == 3

    def test_palette_exists(self, qtbot):
        """Левая панель — PluginPalette."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        assert isinstance(tab._palette, PluginPalette)

    def test_graphview_exists(self, qtbot):
        """Центральная панель — GraphView."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        assert isinstance(tab._view, GraphView)

    def test_inspector_exists(self, qtbot):
        """Правая панель — NodeInspectorPanel."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        assert isinstance(tab._inspector, NodeInspectorPanel)

    def test_splitter_initial_sizes(self, qtbot):
        """Splitter имеет начальные размеры для всех 3 панелей."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        sizes = tab._splitter.sizes()
        assert len(sizes) == 3
        # Все размеры >= 0 (может быть 0 в headless Qt)
        assert all(s >= 0 for s in sizes)


class TestPipelineTabScene:
    def test_scene_populated(self, qtbot):
        """Сцена содержит ноды и edges из topology."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab._scene.node_count() == 2
        assert tab._scene.edge_count() == 1

    def test_empty_topology(self, qtbot):
        """Пустая topology — сцена пуста."""
        ctx = _make_full_ctx(topology={"processes": [], "wires": []})
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab._scene.node_count() == 0
        assert tab._scene.edge_count() == 0


class TestPipelineTabToolbar:
    def test_toolbar_zoom_in(self, qtbot):
        """zoom_in не падает."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        old_zoom = tab._view._current_zoom
        tab._on_toolbar_action("zoom_in")
        assert tab._view._current_zoom >= old_zoom

    def test_toolbar_zoom_out(self, qtbot):
        """zoom_out не падает."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("zoom_out")
        # Просто убеждаемся, что нет исключений

    def test_toolbar_fit(self, qtbot):
        """fit не падает."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("fit")

    def test_toolbar_validate(self, qtbot, monkeypatch):
        """validate не падает (QMessageBox патчится)."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)

        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: None)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: None)

        # Не должен падать с исключением
        tab._on_toolbar_action("validate")

    def test_toolbar_validate_no_errors(self, qtbot, monkeypatch):
        """validate с пустой topology не показывает ошибок."""
        ctx = _make_full_ctx(topology={"processes": [], "wires": []})
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)

        shown_info = []

        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: shown_info.append("info"))
        monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: shown_info.append("warning"))

        tab._on_toolbar_action("validate")
        # Пустая topology валидна — должно быть information, не warning
        assert "warning" not in shown_info

    def test_toolbar_auto_layout(self, qtbot):
        """auto_layout не падает."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("auto_layout")

    def test_toolbar_delete_no_selection(self, qtbot):
        """delete без выбора не падает."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("delete")


class TestPipelineTabInspector:
    def test_selection_shows_inspector(self, qtbot):
        """Выбор ноды через show_node заполняет инспектор."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)

        # Симулируем выбор: вызываем show_node напрямую
        tab._inspector.show_node("camera", "source", plugins=[{"plugin_name": "capture"}])
        assert tab._inspector.current_process == "camera"

    def test_deselection_clears_inspector(self, qtbot):
        """Отмена выбора → placeholder (current_process пустой)."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)

        # Показать ноду, потом очистить
        tab._inspector.show_node("camera", "source")
        tab._inspector.clear()

        assert tab._inspector.current_process == ""

    def test_on_selection_changed_empty(self, qtbot):
        """_on_selection_changed при пустом выборе не падает."""
        ctx = _make_full_ctx()
        tab = PipelineTab.create(ctx)
        qtbot.addWidget(tab)

        # Без выбора — должен вызвать clear
        tab._on_selection_changed()
        assert tab._inspector.current_process == ""
