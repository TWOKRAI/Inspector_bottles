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


_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "AppHeaderWidget": (".app_header", "AppHeaderWidget"),
    "HeaderModeToggle": (".app_header", "HeaderModeToggle"),
    "InfoTickerWidget": (".app_header", "InfoTickerWidget"),
    "StatusStripWidget": (".app_header", "StatusStripWidget"),
    "RecordingIndicator": (".recording_indicator", "RecordingIndicator"),
    "RecordingIndicatorConfig": (".recording_indicator", "RecordingIndicatorConfig"),
    "SearchFilterBar": (".search_filter_bar", "SearchFilterBar"),
    "apply_filter": (".search_filter_bar", "apply_filter"),
    "CollapsibleSidePanel": (".side_panels", "CollapsibleSidePanel"),
    "ViewModeToggle": (".view_mode_toggle", "ViewModeToggle"),
    "WatchdogOverlay": (".watchdog_overlay", "WatchdogOverlay"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_ATTRS:
        module_path, class_name = _LAZY_ATTRS[name]
        import importlib
        mod = importlib.import_module(module_path, package=__name__)
        return getattr(mod, class_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = sorted(_LAZY_ATTRS.keys())
