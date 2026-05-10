"""Тесты для DisplaysTab."""
from __future__ import annotations
from unittest.mock import MagicMock
import pytest
from multiprocess_prototype.frontend.widgets.tabs.displays.tab import DisplaysTab
from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import DisplaysPresenter, DISPLAY_PRESETS


def _make_mock_ctx(processes=None):
    ctx = MagicMock()
    # Используем явную проверку на None, чтобы пустой список [] не заменялся дефолтом
    if processes is None:
        processes = [
            {"process_name": "camera_0"},
            {"process_name": "processor"},
        ]
    ctx.config = {
        "topology": {
            "processes": processes,
        },
    }
    ctx.extras = {}
    ctx.bindings.return_value = None
    return ctx


class TestDisplaysPresenter:
    def test_get_available_sources(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        sources = p.get_available_sources()
        assert "camera_0" in sources
        assert "processor" in sources

    def test_apply_preset_1x1(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        slots = p.apply_preset("1×1")
        assert len(slots) == 1
        assert slots[0]["slot_id"] == "main"

    def test_apply_preset_2x2(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        slots = p.apply_preset("2×2")
        assert len(slots) == 4

    def test_apply_preset_none(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        slots = p.apply_preset("none")
        assert len(slots) == 0

    def test_add_slot(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        slot = p.add_slot("custom")
        assert slot["slot_id"] == "custom"
        assert len(p.slots) == 1

    def test_add_slot_auto_name(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        slot = p.add_slot()
        assert slot["slot_id"] == "display_0"

    def test_remove_slot(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        p.add_slot("a")
        p.add_slot("b")
        p.remove_slot(0)
        assert len(p.slots) == 1
        assert p.slots[0]["slot_id"] == "b"

    def test_set_slot_source(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        p.add_slot("main")
        p.set_slot_source(0, "camera_0")
        assert p.slots[0]["source"] == "camera_0"

    def test_remove_out_of_range(self):
        ctx = _make_mock_ctx()
        p = DisplaysPresenter(ctx)
        p.remove_slot(99)  # не должно упасть

    def test_no_topology(self):
        ctx = _make_mock_ctx(processes=[])
        p = DisplaysPresenter(ctx)
        assert p.get_available_sources() == []


class TestDisplaysTab:
    def test_create(self, qtbot):
        ctx = _make_mock_ctx()
        tab = DisplaysTab.create(ctx)
        qtbot.addWidget(tab)
        assert tab is not None

    def test_preset_selection(self, qtbot):
        ctx = _make_mock_ctx()
        tab = DisplaysTab(ctx)
        qtbot.addWidget(tab)
        tab._on_preset_selected(1)  # "1×1"
        assert tab._table.row_count() == 1

    def test_add_slot(self, qtbot):
        ctx = _make_mock_ctx()
        tab = DisplaysTab(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("add_slot")
        assert tab._table.row_count() == 1

    def test_remove_slot(self, qtbot):
        ctx = _make_mock_ctx()
        tab = DisplaysTab(ctx)
        qtbot.addWidget(tab)
        tab._on_toolbar_action("add_slot")
        tab._on_toolbar_action("add_slot")
        tab._table._table.selectRow(0)
        tab._on_toolbar_action("remove_slot")
        assert tab._table.row_count() == 1

    def test_empty_topology(self, qtbot):
        ctx = _make_mock_ctx(processes=[])
        tab = DisplaysTab(ctx)
        qtbot.addWidget(tab)
        # Не должно упасть
