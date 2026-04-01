# multiprocess_prototype/frontend/windows/main_window/
"""Главное окно: UI + конфиги одной feature-папкой."""

from .config import AppHeaderConfig, ImagePanelConfig, ImageSlotConfig, MainWindowConfig, WindowConfig
from .tab_factory import TabWidgetFactory, create_tab_widget_factory
from .window import MainWindow

__all__ = [
    "MainWindow",
    "MainWindowConfig",
    "AppHeaderConfig",
    "WindowConfig",
    "ImagePanelConfig",
    "ImageSlotConfig",
    "TabWidgetFactory",
    "create_tab_widget_factory",
]
