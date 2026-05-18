"""Backward-compat: реэкспорт StandardTabLayout из framework. См. ADR-127."""

from multiprocess_framework.modules.frontend_module.widgets.tabs.tab_layouts.standard_layout import StandardTabLayout  # noqa: F401

__all__ = ["StandardTabLayout"]
