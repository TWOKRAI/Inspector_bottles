"""Реэкспорт chrome-виджетов из фреймворка.

Оригинальные виджеты живут в frontend_module.widgets.chrome.
"""
from multiprocess_framework.modules.frontend_module.widgets.chrome import (
    AppHeaderWidget,
    HeaderModeToggle,
    InfoTickerWidget,
    StatusStripWidget,
    RecordingIndicator,
    RecordingIndicatorConfig,
    SearchFilterBar,
    apply_filter,
    CollapsibleSidePanel,
    ViewModeToggle,
    WatchdogOverlay,
)

__all__ = [
    "AppHeaderWidget",
    "HeaderModeToggle",
    "InfoTickerWidget",
    "StatusStripWidget",
    "RecordingIndicator",
    "RecordingIndicatorConfig",
    "SearchFilterBar",
    "apply_filter",
    "CollapsibleSidePanel",
    "ViewModeToggle",
    "WatchdogOverlay",
]
