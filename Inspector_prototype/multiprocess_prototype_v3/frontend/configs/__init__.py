# multiprocess_prototype_v3/frontend/configs/__init__.py
"""Композиция UI (FrontendConfig). Конфиг процесса gui — ``GuiConfig`` в ``backend.processes.gui.gui_config``."""

from .frontend_config import FrontendConfig, build_frontend_config

__all__ = ["FrontendConfig", "build_frontend_config"]
