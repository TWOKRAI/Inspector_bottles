# multiprocess_prototype/frontend/configs/__init__.py
"""Конфигурация frontend — схемы на базе data_schema_module."""

from .config import GuiConfigFrontend
from .frontend_config import FrontendConfig, build_frontend_config

__all__ = [
    "GuiConfigFrontend",
    "FrontendConfig",
    "build_frontend_config",
]
