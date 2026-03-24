# multiprocess_prototype/tests/test_frontend_app_context.py
"""FrontendAppContext + фабрика вкладок (контракт без полного main)."""

from __future__ import annotations

import os
import sys

if sys.platform != "win32" and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from multiprocess_prototype.tests.support.gui_env import gui_display_available

pytestmark = pytest.mark.skipif(
    not gui_display_available(),
    reason="GUI requires display or QT_QPA_PLATFORM=offscreen",
)


def test_create_tab_widget_factory_uses_frontend_app_context():
    from PyQt5.QtWidgets import QApplication

    from multiprocess_prototype.frontend.app_context import FrontendAppContext
    from multiprocess_prototype.frontend.windows.main_window.tab_factory import (
        create_tab_widget_factory,
    )

    _ = QApplication.instance() or QApplication([])
    ctx = FrontendAppContext(
        config={
            "recipes_tab": {},
            "settings_tab": {},
            "camera_tab": {},
            "recipe_access": {},
        },
        registers_manager=None,
        camera_callbacks_map={},
        camera_type="simulator",
        recipe_manager=None,
        command_handler=None,
    )
    factory = create_tab_widget_factory(ctx)
    w = factory("processing", {})
    assert w is not None
