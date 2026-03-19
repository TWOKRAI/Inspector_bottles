# multiprocess_prototype/frontend/configs/main_window/main_window_config.py
"""
MainWindowConfig — композиция конфигов MainWindow.

Объединяет WindowConfig, HeaderConfig, ImagePanelConfig.
"""

from pydantic import Field

from multiprocess_framework.refactored.modules.data_schema_module import SchemaBase, register_schema

from .window_config import WindowConfig
from .header_config import HeaderConfig, get_default_header
from .image_panel_config import ImagePanelConfig


@register_schema("MainWindowConfig")
class MainWindowConfig(SchemaBase):
    """Конфигурация MainWindow: window + header + image_panel."""

    window: WindowConfig = Field(default_factory=WindowConfig)
    header: HeaderConfig = Field(default_factory=get_default_header)
    image_panel: ImagePanelConfig = Field(default_factory=ImagePanelConfig)
