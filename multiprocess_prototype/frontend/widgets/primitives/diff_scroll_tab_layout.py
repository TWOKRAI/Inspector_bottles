"""Backward-compat: реэкспорт DiffScrollTabLayout из framework. См. ADR-127."""

from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_layouts.diff_scroll_layout import (
    DiffScrollTabLayout,
)  # noqa: F401

__all__ = ["DiffScrollTabLayout"]
