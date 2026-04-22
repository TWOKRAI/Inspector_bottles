# multiprocess_prototype/tests/test_ui_diagnostics.py
"""Опциональная телеметрия UI (WidgetSignalBus + шапка)."""

from __future__ import annotations

import os
import sys

# Linux CI без DISPLAY: offscreen до импорта Qt
if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from multiprocess_prototype.tests.support.gui_env import gui_display_available

pytestmark = pytest.mark.skipif(
    not gui_display_available(),
    reason="GUI requires display or QT_QPA_PLATFORM=offscreen",
)


def test_attach_ui_diagnostics_disabled_returns_none():
    from PyQt5.QtWidgets import QApplication

    from multiprocess_prototype.frontend.diagnostics import attach_ui_diagnostics
    from multiprocess_prototype.frontend.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow(
        config={
            "window": {"title": "T", "min_width": 320, "min_height": 240},
            "header": {},
            "image_panel": {},
            "tabs": [],
        },
        camera_callbacks_map={},
        camera_type="simulator",
    )
    assert attach_ui_diagnostics(win, {}) is None
    assert attach_ui_diagnostics(win, {"ui_diagnostics": {}}) is None
    assert attach_ui_diagnostics(win, {"ui_diagnostics": {"enabled": False}}) is None


def test_attach_ui_diagnostics_buffers_tab_and_header_events():
    from PyQt5.QtWidgets import QApplication

    from multiprocess_prototype.frontend.diagnostics import attach_ui_diagnostics
    from multiprocess_prototype.frontend.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow(
        config={
            "window": {"title": "T", "min_width": 320, "min_height": 240},
            "header": {},
            "image_panel": {},
            "tabs": [],
        },
        camera_callbacks_map={},
        camera_type="simulator",
    )
    session = attach_ui_diagnostics(
        win,
        {"ui_diagnostics": {"enabled": True, "buffer_max": 20}},
    )
    assert session is not None
    win.tab_widget.emit_widget_event("tab_widget.unit", {"k": 1})
    win._header.action_triggered.emit("nav_test")
    try:
        assert ("tab_widget.unit", {"k": 1}) in session.recent_events
        assert any(
            e[0] == "header.action_triggered" and e[1] == {"action_id": "nav_test"}
            for e in session.recent_events
        )
    finally:
        session.disconnect()


def test_include_prefixes_filters_buffer():
    from PyQt5.QtWidgets import QApplication

    from multiprocess_prototype.frontend.diagnostics import attach_ui_diagnostics
    from multiprocess_prototype.frontend.windows.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow(
        config={
            "window": {"title": "T", "min_width": 320, "min_height": 240},
            "header": {},
            "image_panel": {},
            "tabs": [],
        },
        camera_callbacks_map={},
        camera_type="simulator",
    )
    session = attach_ui_diagnostics(
        win,
        {
            "ui_diagnostics": {
                "enabled": True,
                "buffer_max": 20,
                "include_prefixes": ["tab_widget."],
            }
        },
    )
    assert session is not None
    win.tab_widget.emit_widget_event("noise.other", {})
    win.tab_widget.emit_widget_event("tab_widget.keep", {})
    try:
        ids = [e[0] for e in session.recent_events]
        assert "tab_widget.keep" in ids
        assert "noise.other" not in ids
    finally:
        session.disconnect()
