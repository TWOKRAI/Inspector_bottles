# -*- coding: utf-8 -*-
"""
LEGACY Gen-1 (frozen 2026-07-18) — FrontendManagerConfig, ThreadManagerConfig,
WindowManagerConfig. 0 потребителей вообще (даже внутри application/) — см.
frontend_module/STATUS.md.
"""

from .frontend_manager_config import FrontendManagerConfig
from .thread_manager_config import ThreadManagerConfig
from .window_manager_config import WindowManagerConfig

__all__ = ["FrontendManagerConfig", "ThreadManagerConfig", "WindowManagerConfig"]
