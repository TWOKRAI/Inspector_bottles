# multiprocess_prototype/frontend/configs/__init__.py
"""Корневая конфигурация frontend-процесса (композиция); секции UI — в widgets/ и windows/."""

from .config import GuiConfigFrontend
from .frontend_config import FrontendConfig, build_frontend_config

__all__ = [
    "GuiConfigFrontend",
    "FrontendConfig",
    "build_frontend_config",
]
