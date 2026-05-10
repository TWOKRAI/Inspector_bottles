"""Вкладка Display — управление окнами отображения."""
from __future__ import annotations

from .schemas import DisplayTabConfig, default_tab_item
from .widget import DisplayTabWidget

__all__ = ["DisplayTabConfig", "DisplayTabWidget", "default_tab_item"]
