"""Chrome widgets — заголовок приложения, боковые панели, оверлеи и сквозные UI-элементы.

Реэкспорт Qt-классов — **ленивый** (через `__getattr__`), чтобы pure-Python тесты
могли импортировать `widgets.chrome` без поднятия PySide6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — только для type-checkers
    from .app_header import (
        AppHeaderWidget,
        HeaderModeToggle,
        InfoTickerWidget,
        StatusStripWidget,
    )
    from .recording_indicator import RecordingIndicator, RecordingIndicatorConfig
    from .search_filter_bar import SearchFilterBar, apply_filter
    from .side_panels import CollapsibleSidePanel
    from .view_mode_toggle import ViewModeToggle
    from .watchdog_overlay import WatchdogOverlay


_LAZY_ATTRS: dict[str, str] = {
    "AppHeaderWidget": "app_header",
    "HeaderModeToggle": "app_header",
    "InfoTickerWidget": "app_header",
    "StatusStripWidget": "app_header",
    "RecordingIndicator": "recording_indicator",
    "RecordingIndicatorConfig": "recording_indicator",
    "SearchFilterBar": "search_filter_bar",
    "apply_filter": "search_filter_bar",
    "CollapsibleSidePanel": "side_panels",
    "ViewModeToggle": "view_mode_toggle",
    "WatchdogOverlay": "watchdog_overlay",
}


def __getattr__(name: str) -> Any:
    submod_name = _LAZY_ATTRS.get(name)
    if submod_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    mod = import_module(f".{submod_name}", package=__name__)
    return getattr(mod, name)


__all__ = sorted(_LAZY_ATTRS.keys())
