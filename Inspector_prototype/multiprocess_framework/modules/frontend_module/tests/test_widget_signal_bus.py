# multiprocess_framework\modules\frontend_module\tests\test_widget_signal_bus.py
# -*- coding: utf-8 -*-
"""Смоук: WidgetSignalBus, TabWidget.emit_widget_event без цикла импорта с BaseWidget."""
from __future__ import annotations

from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_widget import TabWidget
from multiprocess_framework.modules.frontend_module.widgets.widget_signal_bus import WidgetSignalBus


def test_widget_signal_bus_importable() -> None:
    assert WidgetSignalBus is not None


def test_tab_widget_has_signal_bus() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    tw = TabWidget()
    assert tw.signal_bus is not None
    received: list[tuple[str, object]] = []

    def on_event(eid: str, payload: object) -> None:
        received.append((eid, payload))

    tw.signal_bus.event_emitted.connect(on_event)
    tw.emit_widget_event("test.event", {"x": 1})
    assert received == [("test.event", {"x": 1})]
