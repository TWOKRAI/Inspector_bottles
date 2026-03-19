# multiprocess_prototype/frontend/configs/main_window/__init__.py
"""Конфигурации компонентов MainWindow."""

from .window_config import WindowConfig
from .header_config import (
    AdminButtonConfig,
    AppHeaderConfig,
    HeaderButtonItem,
    HeaderConfig,
    LogoConfig,
    get_default_header,
)
from .image_panel_config import ImagePanelConfig, ImageSlotConfig
from .main_window_config import MainWindowConfig

__all__ = [
    "WindowConfig",
    "HeaderConfig",
    "HeaderButtonItem",
    "AdminButtonConfig",
    "LogoConfig",
    "AppHeaderConfig",
    "get_default_header",
    "ImagePanelConfig",
    "ImageSlotConfig",
    "MainWindowConfig",
]
